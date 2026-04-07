import pandas as pd
import numpy as np
import yfinance as yf

from ta.momentum import RSIIndicator
from ta.trend import SMAIndicator

from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

# -----------------------------
# 1. Fetch Data
# -----------------------------
def fetch_data(symbol="AAPL", period="6mo", interval="1d"):
    df = yf.download(symbol, period=period, interval=interval)
    df = df.dropna()
    return df

# -----------------------------
# 2. Feature Engineering
# -----------------------------
def add_features(df):
    df["returns"] = df["Close"].pct_change()

    # RSI
    rsi = RSIIndicator(close=df["Close"], window=14)
    df["rsi"] = rsi.rsi()

    # Moving averages
    sma_10 = SMAIndicator(close=df["Close"], window=10)
    sma_20 = SMAIndicator(close=df["Close"], window=20)

    df["sma_10"] = sma_10.sma_indicator()
    df["sma_20"] = sma_20.sma_indicator()

    # Price vs MA
    df["price_sma10_diff"] = df["Close"] - df["sma_10"]
    df["price_sma20_diff"] = df["Close"] - df["sma_20"]

    df = df.dropna()
    return df

# -----------------------------
# 3. Create Labels
# -----------------------------
def create_labels(df, threshold=0.01):
    df["future_return"] = df["Close"].shift(-1) / df["Close"] - 1

    def label(x):
        if x > threshold:
            return 1   # CALL
        elif x < -threshold:
            return -1  # PUT
        else:
            return 0   # NO TRADE

    df["signal"] = df["future_return"].apply(label)
    df = df.dropna()
    return df

# -----------------------------
# 4. Train Model
# -----------------------------
def train_model(df):
    features = [
        "returns",
        "rsi",
        "price_sma10_diff",
        "price_sma20_diff"
    ]

    X = df[features]
    y = df["signal"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)

    print("\n📊 Model Performance:")
    print(classification_report(y_test, preds))

    return model, features

# -----------------------------
# 5. Predict Latest Signal
# -----------------------------
def predict_latest(df, model, features):
    latest = df.iloc[-1][features].values.reshape(1, -1)
    pred = model.predict(latest)[0]
    prob = model.predict_proba(latest).max()

    mapping = {
        1: "BUY CALL",
        -1: "BUY PUT",
        0: "NO TRADE"
    }

    return mapping[pred], prob

# -----------------------------
# 6. Run Pipeline
# -----------------------------
if __name__ == "__main__":
    df = fetch_data("AAPL")
    df = add_features(df)
    df = create_labels(df)

    model, features = train_model(df)

    signal, confidence = predict_latest(df, model, features)

    print(f"\n📈 Latest Signal: {signal}")
    print(f"Confidence: {confidence:.2f}")