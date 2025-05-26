import logging
import os

LOG_FILE = os.getenv("INFRACTL_LOG_FILE", "infractl-audit.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("infractl")


import requests

def send_slack_alert(webhook_url, message):
    payload = {"text": message}
    try:
        response = requests.post(webhook_url, json=payload)
        if response.status_code != 200:
            logger.error(f"Slack webhook failed: {response.status_code} {response.text}")
        else:
            logger.info("Slack alert sent successfully.")
    except Exception as e:
        logger.error(f"Slack webhook error: {str(e)}")


def export_summary_to_json(data, filename="summary.json"):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"✅ Summary exported to {filename}")

def export_summary_to_csv(data, filename="summary.csv"):
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric", "Value"])
        for key, value in data.items():
            writer.writerow([key, value])
    logger.info(f"✅ Summary exported to {filename}")
