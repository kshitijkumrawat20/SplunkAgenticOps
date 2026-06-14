import random
import time
from datetime import datetime

LOG_FILE = "./logs/app.log"

NORMAL_EVENTS = [
    "INFO auth-service User Login",
    "INFO order-service Order Created",
    "INFO payment-service Payment Success",
    "INFO inventory-service Inventory Updated",
]

DATABASE_ERRORS = [
    "ERROR order-service Database Timeout",
    "ERROR order-service Connection Pool Exhausted",
    "ERROR order-service Query Timeout",
]

REDIS_ERRORS = [
    "ERROR cart-service Redis Connection Failed",
    "ERROR cart-service Cache Unavailable",
]

PAYMENT_ERRORS = [
    "ERROR payment-service Payment Gateway Timeout",
    "ERROR payment-service Provider Unreachable",
]

incident_mode = "normal"

while True:

    if incident_mode == "normal":
        event = random.choice(NORMAL_EVENTS)

    elif incident_mode == "database":
        event = random.choice(DATABASE_ERRORS)

    elif incident_mode == "redis":
        event = random.choice(REDIS_ERRORS)

    elif incident_mode == "payment":
        event = random.choice(PAYMENT_ERRORS)

    with open(LOG_FILE, "a") as f:
        f.write(f"{datetime.now()} {event}\n")

    print(event)

    time.sleep(1)