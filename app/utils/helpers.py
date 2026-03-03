import requests
import urllib.parse

def shorten_url(long_url, logger=None):
    """
    Shorten a URL using is.gd (or TinyURL as fallback).
    Args:
        long_url (str): The original URL to shorten.
        logger: Optional logger (e.g., from AppDaemon) for logging errors.
    Returns:
        str: Shortened URL or original URL on failure.
    """
    # URL-encode the long_url to handle special characters
    encoded_url = urllib.parse.quote(long_url)
    
    # Try is.gd first (shorter URLs, no API key needed)
    try:
        response = requests.get(f"https://is.gd/create.php?format=simple&url={encoded_url}", timeout=5)
        if response.status_code == 200 and response.text.startswith("https://"):
            if logger:
                logger(f"Shortened URL to: {response.text}", level="DEBUG")
            return response.text
        else:
            if logger:
                logger(f"is.gd failed: {response.status_code} {response.text}", level="WARNING")
    except requests.RequestException as e:
        if logger:
            logger(f"Error with is.gd: {e}", level="WARNING")

    # Fallback to TinyURL
    try:
        response = requests.get(f"http://tinyurl.com/api-create.php?url={encoded_url}", timeout=5)
        if response.status_code == 200 and response.text.startswith("https://"):
            if logger:
                logger(f"Shortened URL to: {response.text}", level="DEBUG")
            return response.text
        else:
            if logger:
                logger(f"TinyURL failed: {response.status_code}", level="WARNING")
    except requests.RequestException as e:
        if logger:
            logger(f"Error with TinyURL: {e}", level="WARNING")

    # Fallback to original URL
    if logger:
        logger(f"Failed to shorten URL, using original: {long_url}", level="WARNING")
    return long_url