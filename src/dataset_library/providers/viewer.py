"""Hugging Face's dataset viewer (datasets-server): column types and first rows.

Only https://datasets-server.huggingface.co is called. Any answer but 200 —
the viewer cannot read the dataset (501), it is gated (401), or it does not
exist — is `ViewerUnavailable`: the caller shows the card without a preview."""
import requests

from ..errors import ProviderRateLimited

VIEWER = "https://datasets-server.huggingface.co/"
TIMEOUT = 10


class ViewerUnavailable(Exception):
    pass


def get(endpoint, **params):
    try:
        response = requests.get(VIEWER + endpoint, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ViewerUnavailable(str(exc)) from exc
    if response.status_code == 429:
        raise ProviderRateLimited("Hugging Face is limiting requests")
    if response.status_code != 200:
        raise ViewerUnavailable(f"The viewer answered {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ViewerUnavailable("Unreadable answer") from exc
