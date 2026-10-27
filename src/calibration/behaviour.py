"""Measures browsing / cart / purchase behaviour from a real clickstream dataset.

Supported files (format is detected from the header):
  RetailRocket events.csv   timestamp, visitorid, event (view/addtocart/transaction), itemid, transactionid
  REES46 2019-Oct.csv etc.  event_time, event_type (view/cart/remove_from_cart/purchase), ..., price, user_id, user_session

Large files are read in chunks and a fixed share of users is sampled, so a 5 GB REES46
month runs on a laptop.
"""
import pandas as pd

SESSION_GAP = pd.Timedelta(minutes=30)  # RetailRocket has no session id: new session after 30 min idle


def _detect(path):
    header = pd.read_csv(path, nrows=0).columns
    if {"visitorid", "event", "timestamp"} <= set(header):
        return "retailrocket"
    if {"user_id", "event_type", "event_time"} <= set(header):
        return "rees46"
    raise ValueError(f"{path}: unknown format, columns {list(header)}")


def _load(path, fmt, sample_mod, chunksize=2_000_000):
    parts = []
    if fmt == "retailrocket":
        for ch in pd.read_csv(path, usecols=["timestamp", "visitorid", "event", "transactionid"], chunksize=chunksize):
            ch = ch[ch["visitorid"] % sample_mod == 0]
            parts.append(pd.DataFrame({
                "user": ch["visitorid"],
                "ts": pd.to_datetime(ch["timestamp"], unit="ms"),
                "event": ch["event"].map({"view": "view", "addtocart": "cart", "transaction": "purchase"}),
                "price": float("nan"),
                "session": None,
            }))
    else:
        cols = ["event_time", "event_type", "price", "user_id", "user_session"]
        for ch in pd.read_csv(path, usecols=cols, chunksize=chunksize):
            ch = ch[ch["user_id"] % sample_mod == 0]
            ch = ch[ch["event_type"].isin(["view", "cart", "purchase"])]
            parts.append(pd.DataFrame({
                "user": ch["user_id"],
                "ts": pd.to_datetime(ch["event_time"].str.replace(" UTC", "", regex=False)),
                "event": ch["event_type"],
                "price": ch["price"],
                "session": ch["user_session"],
            }))
    df = pd.concat(parts, ignore_index=True).dropna(subset=["event"])
    df = df.sort_values(["user", "ts"]).reset_index(drop=True)
    if df["session"].isna().all():
        new = (df["user"] != df["user"].shift()) | (df["ts"] - df["ts"].shift() > SESSION_GAP)
        df["session"] = new.cumsum()
    return df


def _pct(series, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    if series.empty:
        return None
    return {f"p{int(q * 100)}": round(float(series.quantile(q)), 2) for q in qs}


def measure(path, sample=1.0):
    fmt = _detect(path)
    sample_mod = max(1, round(1 / sample))
    df = _load(path, fmt, sample_mod)
    span_days = max((df["ts"].max() - df["ts"].min()).total_seconds() / 86400, 1)

    sessions = df.groupby(["user", "session"]).agg(
        start=("ts", "min"),
        has_cart=("event", lambda e: (e == "cart").any()),
        has_purchase=("event", lambda e: (e == "purchase").any()),
    ).reset_index()
    no_buy = sessions[~sessions["has_purchase"]]
    carted = sessions[sessions["has_cart"]]

    per_user = sessions.groupby("user").agg(
        n_sessions=("session", "size"), n_purchase_sessions=("has_purchase", "sum"),
        first=("start", "min"), last=("start", "max"),
    )
    # Rate while the user is active (first to last visit, at least a week), not over the
    # whole dataset: a customer active for 2 weeks of a 4-month file isn't a light browser.
    active_days = ((per_user["last"] - per_user["first"]).dt.total_seconds() / 86400).clip(lower=7)
    per_user["sessions_per_week"] = per_user["n_sessions"] / (active_days / 7)
    returning = per_user[per_user["n_sessions"] >= 2]
    buyers = per_user[per_user["n_purchase_sessions"] > 0]
    heavy = per_user[per_user["n_sessions"] >= 5]

    # Days between purchases, for customers who bought on 2+ different days.
    buy_days = sessions[sessions["has_purchase"]].assign(day=lambda s: s["start"].dt.normalize())
    buy_days = buy_days.drop_duplicates(["user", "day"]).sort_values(["user", "day"])
    buy_days["gap"] = buy_days.groupby("user")["day"].diff().dt.days
    user_gap = buy_days.dropna(subset=["gap"]).groupby("user")["gap"].mean()

    out = {
        "source": str(path),
        "format": fmt,
        "sampled_users_share": round(1 / sample_mod, 4),
        "days_covered": round(span_days, 1),
        "users": int(len(per_user)),
        "sessions": int(len(sessions)),
        "events": int(len(df)),
        "session_purchase_rate": round(float(sessions["has_purchase"].mean()), 4),
        "cart_abandonment_rate": round(float((~carted["has_purchase"]).mean()), 4) if len(carted) else None,
        "abandon_rate_per_non_buying_session": round(float(no_buy["has_cart"].mean()), 4) if len(no_buy) else None,
        "buyer_share": round(len(buyers) / len(per_user), 4),
        "repeat_buyer_share": round(float((buyers["n_purchase_sessions"] >= 2).mean()), 4) if len(buyers) else None,
        "window_shopper_share_of_heavy_browsers": round(float((heavy["n_purchase_sessions"] == 0).mean()), 4) if len(heavy) else None,
        "sessions_per_week_returning_users": _pct(returning["sessions_per_week"]),
        "order_gap_days_repeat_buyers": _pct(user_gap),
        "repeat_buyers_with_gap": int(len(user_gap)),
    }
    if fmt == "rees46":
        purchases = df[df["event"] == "purchase"].groupby(["user", "session"])["price"].sum()
        out["order_value_spread"] = _pct(purchases / purchases.median()) if len(purchases) else None
    return out
