import logging

import requests
import urllib.parse

_logger = logging.getLogger(__name__)

# Providers tried in order. All return the short URL as plain text and
# redirect visitors directly (no interstitial page).
_SHORTENERS = [
    ("is.gd", "https://is.gd/create.php?format=simple&url={url}"),
    ("da.gd", "https://da.gd/s?url={url}"),
    ("TinyURL", "https://tinyurl.com/api-create.php?url={url}"),
]


def shorten_url(long_url, logger=None):
    """
    Shorten a URL trying is.gd, then da.gd, then TinyURL.
    Args:
        long_url (str): The original URL to shorten.
        logger: Optional logger (e.g., from AppDaemon) for logging errors.
    Returns:
        str: Shortened URL or original URL on failure.
    """
    def _log(msg, level="WARNING"):
        if logger:
            logger(msg, level=level)
        getattr(_logger, level.lower(), _logger.warning)(msg)

    # URL-encode the long_url to handle special characters
    encoded_url = urllib.parse.quote(long_url)

    for name, api in _SHORTENERS:
        try:
            response = requests.get(api.format(url=encoded_url), timeout=5)
            short = response.text.strip()
            if response.status_code == 200 and short.startswith("https://"):
                _log(f"Shortened URL via {name}: {short}", level="DEBUG")
                return short
            _log(f"{name} failed: {response.status_code} {short[:100]}")
        except requests.RequestException as e:
            _log(f"Error with {name}: {e}")

    _log(f"Failed to shorten URL, using original: {long_url}")
    return long_url
