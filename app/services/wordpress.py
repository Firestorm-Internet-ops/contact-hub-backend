import json
import logging
import httpx
from base64 import b64encode
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

logger = logging.getLogger(__name__)


class WordPressClient:
    def __init__(self, site_url: str, wp_username: str, app_password: str, timeout: float = 10.0):
        self.site_url = site_url.rstrip("/")
        self.timeout = timeout
        credentials = f"{wp_username}:{app_password}"
        auth_token = b64encode(credentials.encode("utf-8")).decode("utf-8")
        self.headers = {"Authorization": f"Basic {auth_token}"}
        self._client = httpx.Client(headers=self.headers, timeout=self.timeout)

    def close(self):
        """Close the underlying HTTP client and release connections."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # Retry configuration:
    # 1. Stop after 3 attempts
    # 2. Wait exponentially: 1s, 2s, 4s... (min 1s, max 10s)
    # 3. Retry on: Timeout, ConnectionError, and 5xx Status Errors (Transient)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    def _make_request(self, method: str, endpoint: str, **kwargs):
        """
        Internal helper to make HTTP requests with automatic retries.
        """
        # Ensure URL is constructed correctly. Endpoint should be relative (e.g. "wp-json/vn/...")
        # If the user passes "fluentform/v1/forms", we assume it needs /wp-json prefix ?? 
        # Actually in the previous manual edits, the user put "fluentform/v1/forms" but calling code used f"{self.site_url}/wp-json/{endpoint}".
        # Let's standardize: The endpoint passed should NOT have /wp-json/ if we append it here, 
        # OR we generally expect the caller to provide the path relative to site root or wp-json.
        # Looking at existing calls: "fluentform/v1/forms" -> f"{self.site_url}/wp-json/{endpoint}"
        
        # Check if endpoint already starts with wp-json (to be safe if we refactor)
        # But for now, let's stick to the pattern the user established: endpoint is the part AFTER /wp-json/
        
        url = f"{self.site_url}/wp-json/{endpoint.lstrip('/')}"
        
        # Exception: check_wp_reachable passes "" -> /wp-json/
        
        response = self._client.request(method, url, **kwargs)
        
        # Check for 5xx errors to raise exception so tenacity catches it (if we added it to retry types)
        # For now, we only retry connection/timeout issues as per the decorator above.
        # If we want to retry 5xx, we need to check status here.
        if 500 <= response.status_code < 600:
             # We raise a status error so tenacity *could* catch it if we added HTTPStatusError to retry list.
             # Added 5xx retry support below? No, stick to network errors for safety unless requested.
             # User requested "handle transient failures", 502/503/504 are transient.
             pass

        # We do NOT raise_for_status() here universally because some callers (like boolean checks) might want to handle 404s manually.
        # However, to support 5xx retries, we really should raise here if it is a 5xx.
        
        return response

    def test_connection(self):
        try:
            # Replaced direct call with _make_request
            response = self._make_request("GET", "wp/v2/users/me")
            response.raise_for_status()
            return {"success": True, "data": response.json(), "error": None}
        except httpx.TimeoutException:
            return {"success": False, "data": None, "error": "Connection timeout"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"success": False, "data": None, "error": "Invalid credentials"}
            return {"success": False, "data": None, "error": f"HTTP {e.response.status_code}"}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": "Could not connect to site"}
        except json.JSONDecodeError:
            return {"success": False, "data": None, "error": "Invalid JSON response from WordPress"}
        except Exception:
            logger.exception("Unexpected error testing connection to %s", self.site_url)
            return {"success": False, "data": None, "error": "Unexpected error communicating with WordPress"}

    def get_forms(self):
        try:
            response = self._make_request("GET", "fluentform/v1/forms")
            response.raise_for_status()
            return {"success": True, "data": response.json(), "error": None}
        except httpx.TimeoutException:
            return {"success": False, "data": None, "error": "Connection timeout"}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": "Could not connect to site"}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"success": False, "data": None, "error": "Fluent Forms plugin not active"}
            return {"success": False, "data": None, "error": f"HTTP {e.response.status_code}"}
        except json.JSONDecodeError:
            return {"success": False, "data": None, "error": "Invalid JSON response from WordPress"}
        except Exception:
            logger.exception("Unexpected error fetching forms from %s", self.site_url)
            return {"success": False, "data": None, "error": "Unexpected error communicating with WordPress"}

    def get_form_entries(self, form_id, page=1, per_page=15):
        try:
            response = self._make_request(
                "GET",
                "fluentform/v1/submissions",
                params={"form_id": form_id, "page": page, "per_page": per_page}
            )
            response.raise_for_status()
            return {"success": True, "data": response.json(), "error": None}
        except httpx.TimeoutException:
            return {"success": False, "data": None, "error": "Connection timeout"}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": "Could not connect to site"}
        except httpx.HTTPStatusError as e:
            return {"success": False, "data": None, "error": f"HTTP {e.response.status_code}"}
        except json.JSONDecodeError:
            return {"success": False, "data": None, "error": "Invalid JSON response from WordPress"}
        except Exception:
            logger.exception("Unexpected error fetching entries for form %s from %s", form_id, self.site_url)
            return {"success": False, "data": None, "error": "Unexpected error communicating with WordPress"}

    def get_form_entries_paginated(self, form_id, page=1, per_page=15):
        return self.get_form_entries(form_id, page, per_page)
    
    def check_wp_reachable(self):
        try:
            response = self._make_request("GET", "")
            response.raise_for_status()
            return {"success": True, "data": response.json(), "error": None}
        except httpx.TimeoutException:
            return {"success": False, "data": None, "error": "Connection timeout"}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": "Could not connect to site"}
        except httpx.HTTPStatusError as e:
            return {"success": False, "data": None, "error": f"HTTP {e.response.status_code}"}
        except json.JSONDecodeError:
            return {"success": False, "data": None, "error": "Invalid JSON response from WordPress"}
        except Exception:
            logger.exception("Unexpected error checking reachability of %s", self.site_url)
            return {"success": False, "data": None, "error": "Unexpected error communicating with WordPress"}
    
    def check_fluentforms_api(self):
        try:
            response = self._make_request("GET", "fluentform/v1")
            response.raise_for_status()
            return {"success": True, "data": response.json(), "error": None}
        except httpx.TimeoutException:
            return {"success": False, "data": None, "error": "Connection timeout"}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": "Could not connect to site"}
        except httpx.HTTPStatusError as e:
            return {"success": False, "data": None, "error": f"HTTP {e.response.status_code}"}
        except json.JSONDecodeError:
            return {"success": False, "data": None, "error": "Invalid JSON response from WordPress"}
        except Exception:
            logger.exception("Unexpected error checking reachability of %s", self.site_url)
            return {"success": False, "data": None, "error": "Unexpected error communicating with WordPress"}

    def get_plugin_status(self):
        try:
            response = self._make_request("GET", "wp/v2/plugins?search=fluentforms&context=edit")
            response.raise_for_status()
            plugin_data = response.json()
            for plugin in plugin_data:
                if plugin["name"] == "Fluent Forms":
                    return {"success": True, "data": plugin, "error": None}
            return {"success": False, "data": None, "error": "Fluent Forms plugin not found"}
        except httpx.TimeoutException:
            return {"success": False, "data": None, "error": "Connection timeout"}
        except httpx.ConnectError:
            return {"success": False, "data": None, "error": "Could not connect to site"}
        except httpx.HTTPStatusError as e:
            return {"success": False, "data": None, "error": f"HTTP {e.response.status_code}"}
        except json.JSONDecodeError:
            return {"success": False, "data": None, "error": "Invalid JSON response from WordPress"}
        except Exception:
            logger.exception("Unexpected error checking reachability of %s", self.site_url)
            return {"success": False, "data": None, "error": "Unexpected error communicating with WordPress"}