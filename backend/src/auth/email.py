import logging

import boto3

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_backend == "console":
        # Local development: no mail server. The link in the body can be copied from the log.
        logger.warning("EMAIL (console backend)\nTo: %s\nSubject: %s\n\n%s", to, subject, body)
        return
    boto3.client("ses", region_name=settings.s3_region).send_email(
        Source=settings.email_sender,
        Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
    )