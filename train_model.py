# train_model.py
# Smart Bus Energy Prediction - ML Model Training
# IEEE paper methodology: Random Forest + feature engineering

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.preprocessing import LabelEncoder
import joblib
import os

print("Loading dataset...")
df = pd.read_csv('../dataset/bus_data.csv')

# Traffic level encode చేయి (text → number)
le = LabelEncoder()
df['traffic_encoded'] = le.fit_transform(df['traffic_level'])
# low=1, normal=2, high=0, jam=3 గా convert అవుతుంది

# Features మరియు Target define చేయి
X = df[['distance_km', 'avg_speed_kmh', 'passenger_count',
        'ac_on', 'ambient_temp_c', 'traffic_encoded']]
y = df['energy_consumed_kwh']

print(f"Total samples: {len(df)}")
print(f"Features: {list(X.columns)}")

# Train/Test split — 80% train, 20% test
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

print(f"\nTraining samples: {len(X_train)}")
print(f"Testing samples:  {len(X_test)}")

# Random Forest Model train చేయి
print("\nTraining Random Forest model...")
model = RandomForestRegressor(
    n_estimators=100,
    random_state=42,
    max_depth=10
)
model.fit(X_train, y_train)

# Model evaluate చేయి
y_pred = model.predict(X_test)
r2  = r2_score(y_test, y_pred)
mae = mean_absolute_error(y_test, y_pred)

print(f"\n=== Model Results ===")
print(f"R² Score  : {r2*100:.1f}%  (higher = better, 90%+ good)")
print(f"MAE       : {mae:.3f} kWh  (lower = better)")

# Feature importance చూపించు
print(f"\n=== Feature Importance ===")
features = ['distance_km','speed','passengers','ac_on','temperature','traffic']
for feat, imp in sorted(zip(features, model.feature_importances_),
                         key=lambda x: x[1], reverse=True):
    print(f"  {feat:15s}: {imp*100:.1f}%")

# Model save చేయి
os.makedirs('saved_model', exist_ok=True)
joblib.dump(model, 'saved_model/energy_model.pkl')
joblib.dump(le,    'saved_model/label_encoder.pkl')
print(f"\nModel saved to ml_model/saved_model/energy_model.pkl")

# Quick prediction test
print(f"\n=== Sample Prediction Test ===")
sample = pd.DataFrame([{
    'distance_km'    : 20,
    'avg_speed_kmh'  : 35,
    'passenger_count': 40,
    'ac_on'          : 1,
    'ambient_temp_c' : 38,
    'traffic_encoded': 0
}])
prediction = model.predict(sample)[0]
print(f"20km, 40 passengers, AC on, 38°C, high traffic")
print(f"Predicted energy: {prediction:.2f} kWh")
print(f"\nDone! Model ready.")