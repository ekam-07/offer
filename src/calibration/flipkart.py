"""Measures category mix, prices and product names from the Flipkart product catalog.

Expected file: flipkart_com-ecommerce_sample.csv (Kaggle: PromptCloudHQ/flipkart-products), with
columns product_name, product_category_tree, retail_price, discounted_price.
"""
import re

import pandas as pd

# Flipkart top-level category -> our category. Anything not listed is ignored.
CATEGORY_MAP = {
    "Clothing": "Fashion", "Footwear": "Fashion", "Jewellery": "Fashion", "Watches": "Fashion",
    "Bags, Wallets & Belts": "Fashion", "Sunglasses": "Fashion", "Eyewear": "Fashion",
    "Mobiles & Accessories": "Mobiles", "Mobiles": "Mobiles", "Tablets": "Mobiles",
    "Computers": "Electronics", "Cameras & Accessories": "Electronics", "Gaming": "Electronics",
    "Audio & Video": "Electronics", "Home Entertainment": "Electronics", "Wearable Smart Devices": "Electronics",
    "Home Decor & Festive Needs": "Home", "Home Furnishing": "Home", "Kitchen & Dining": "Home",
    "Furniture": "Home", "Home Improvement": "Home", "Tools & Hardware": "Home", "Home & Kitchen": "Home",
    "Beauty and Personal Care": "Beauty", "Health & Personal Care Appliances": "Beauty",
    "Books": "Books", "eBooks": "Books",
    "Food & Nutrition": "Grocery", "Grocery": "Grocery", "Household Supplies": "Grocery",
}


def _top_category(tree):
    # '["Clothing >> Women's Clothing >> ..."]' -> 'Clothing'
    m = re.match(r'\s*\[?"?\s*([^>"\]]+?)\s*(>>|"|\]|$)', str(tree))
    return m.group(1).strip() if m else None


def _short_name(name, limit=40):
    name = re.sub(r"\s+", " ", str(name)).strip()
    return name if len(name) <= limit else name[: limit - 1].rsplit(" ", 1)[0]


def measure(path, names_per_category=8, seed=42):
    df = pd.read_csv(path, usecols=["product_name", "product_category_tree", "retail_price", "discounted_price"])
    df["category"] = df["product_category_tree"].map(_top_category).map(CATEGORY_MAP)
    df["price"] = pd.to_numeric(df["discounted_price"], errors="coerce").fillna(pd.to_numeric(df["retail_price"], errors="coerce"))
    df["list_price"] = pd.to_numeric(df["retail_price"], errors="coerce")
    df = df.dropna(subset=["category", "price"])
    df = df[df["price"] > 0]

    overall_median = float(df["price"].median())
    out = {"source": str(path), "products_used": int(len(df)), "overall_median_price_inr": overall_median, "categories": {}}
    for cat, g in df.groupby("category"):
        listed = g.dropna(subset=["list_price"])
        listed = listed[listed["list_price"] > 0]
        discount = (1 - listed["price"] / listed["list_price"]).clip(lower=0)
        names = g["product_name"].drop_duplicates().sample(min(names_per_category, g["product_name"].nunique()), random_state=seed)
        out["categories"][cat] = {
            "products": int(len(g)),
            "share": round(len(g) / len(df), 3),
            "median_price_inr": float(g["price"].median()),
            "p25_price_inr": float(g["price"].quantile(0.25)),
            "p75_price_inr": float(g["price"].quantile(0.75)),
            "median_list_discount_pct": round(float(discount.median()) * 100, 1) if len(discount) else None,
            "sample_products": [_short_name(n) for n in names],
        }
    return out
