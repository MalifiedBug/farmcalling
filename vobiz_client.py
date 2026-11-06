"""
Vobiz Client Module for FarmCalling.
Handles Vobiz REST API communication and VobizXML generation.
"""

import requests
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
import xml.sax.saxutils

logger = logging.getLogger(__name__)

BASE_URL = "https://api.vobiz.ai/api/v1"

class VobizClient:
    def __init__(self, auth_id: str, auth_token: str):
        self.auth_id = auth_id.strip() if auth_id else ""
        self.auth_token = auth_token.strip() if auth_token else ""
        self.headers = {
            "X-Auth-ID": self.auth_id,
            "X-Auth-Token": self.auth_token,
            "Content-Type": "application/json"
        }

    def is_configured(self) -> bool:
        return bool(self.auth_id and self.auth_token)

    def test_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Tests credentials by querying Account, Balance, and Number info.
        Returns: (success: bool, message: str, data: dict)
        """
        if not self.is_configured():
            return False, "Auth ID or Auth Token is missing in Settings.", {}

        try:
            # Query Account info (exact canonical path: lowercase account, no trailing slash)
            url = f"{BASE_URL}/account/{self.auth_id}"
            resp = requests.get(url, headers=self.headers, timeout=8, allow_redirects=False)
            
            if resp.status_code == 200:
                account_data = resp.json()
                
                # Fetch balance
                balance_val = "0.0"
                currency = "INR"
                try:
                    b_url = f"{BASE_URL}/account/{self.auth_id}/balance"
                    b_resp = requests.get(b_url, headers=self.headers, timeout=5, allow_redirects=False)
                    if b_resp.status_code == 200:
                        b_data = b_resp.json()
                        balances = b_data.get("balances", [])
                        if balances and isinstance(balances, list):
                            balance_val = str(balances[0].get("balance", "0.0"))
                            currency = balances[0].get("currency", "INR")
                except Exception as e:
                    logger.warning(f"Failed to fetch balance: {e}")

                # Fetch owned numbers
                numbers = self.get_phone_numbers()

                account_name = account_data.get("name") or account_data.get("company") or self.auth_id
                return True, f"Successfully connected! Verified account for {account_name}.", {
                    "account": account_data,
                    "balance": balance_val,
                    "currency": currency,
                    "numbers": numbers
                }
            elif resp.status_code == 401:
                return False, "Invalid Credentials: Authentication failed (401 Unauthorized).", {}
            elif resp.status_code == 404:
                return False, f"Account '{self.auth_id}' not found (404).", {}
            else:
                return False, f"Vobiz API returned HTTP {resp.status_code}: {resp.text}", {}

        except requests.RequestException as e:
            return False, f"Connection error: {str(e)}", {}

    def get_phone_numbers(self) -> List[str]:
        """Returns list of owned phone numbers."""
        if not self.is_configured():
            return []
        try:
            url = f"{BASE_URL}/Account/{self.auth_id}/numbers"
            resp = requests.get(url, headers=self.headers, timeout=8, allow_redirects=False)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                numbers = []
                for item in items:
                    num = item.get("e164") or item.get("number")
                    if num:
                        numbers.append(num)
                return numbers
        except Exception as e:
            logger.error(f"Error listing numbers: {e}")
        return []

    def make_call(
        self,
        from_number: str,
        to_number: str,
        answer_url: str,
        hangup_url: Optional[str] = None,
        ring_timeout: int = 30,
        time_limit: int = 3600,
        machine_detection: str = "false",
        caller_name: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Initiates an outbound call via Vobiz API.
        POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/
        """
        if not self.is_configured():
            return False, "Vobiz Auth ID and Auth Token are not configured.", {}

        url = f"{BASE_URL}/Account/{self.auth_id}/Call/"
        payload = {
            "from": from_number.strip(),
            "to": to_number.strip(),
            "answer_url": answer_url.strip(),
            "answer_method": "POST",
            "ring_timeout": str(ring_timeout),
            "time_limit": str(time_limit),
            "machine_detection": machine_detection
        }
        if hangup_url:
            payload["hangup_url"] = hangup_url.strip()
            payload["hangup_method"] = "POST"
        if caller_name:
            payload["caller_name"] = caller_name

        try:
            logger.info(f"Firing Vobiz Call to {to_number} from {from_number}")
            resp = requests.post(url, headers=self.headers, json=payload, timeout=12)
            
            if resp.status_code in [200, 201]:
                res_json = resp.json()
                return True, "Call initiated successfully", res_json
            else:
                err_text = resp.text
                try:
                    err_json = resp.json()
                    err_text = err_json.get("error") or err_json.get("message") or resp.text
                except Exception:
                    pass
                return False, f"Vobiz Call Error ({resp.status_code}): {err_text}", {"raw": resp.text}
        except requests.RequestException as e:
            return False, f"Request failed: {str(e)}", {}

    def create_application(
        self,
        app_name: str,
        answer_url: str,
        hangup_url: Optional[str] = None,
        default_number_app: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Creates a Vobiz Application for webhook routing.
        POST https://api.vobiz.ai/api/v1/Account/{auth_id}/Application/
        """
        if not self.is_configured():
            return False, "Vobiz Auth ID and Auth Token are not configured.", {}

        url = f"{BASE_URL}/Account/{self.auth_id}/Application/"
        payload = {
            "app_name": app_name.strip(),
            "answer_url": answer_url.strip(),
            "answer_method": "POST",
            "default_number_app": default_number_app
        }
        if hangup_url:
            payload["hangup_url"] = hangup_url.strip()
            payload["hangup_method"] = "POST"

        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if resp.status_code in [200, 201]:
                return True, "Application created successfully", resp.json()
            else:
                return False, f"Create Application failed ({resp.status_code}): {resp.text}", {}
        except Exception as e:
            return False, f"Request error: {str(e)}", {}

    def list_applications(self) -> List[Dict[str, Any]]:
        """Lists registered Vobiz Applications."""
        if not self.is_configured():
            return []
        try:
            url = f"{BASE_URL}/Account/{self.auth_id}/Application/"
            resp = requests.get(url, headers=self.headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("objects", []) or data.get("items", [])
        except Exception as e:
            logger.error(f"Error listing applications: {e}")
        return []

    @staticmethod
    def generate_play_xml(audio_url: str, loop: int = 1) -> str:
        """
        Generates canonical VobizXML that plays an audio file and terminates the call.
        """
        escaped_url = xml.sax.saxutils.escape(str(audio_url).strip())
        loop_cnt = max(1, int(loop or 1))
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play loop="{loop_cnt}">{escaped_url}</Play>
    <Hangup/>
</Response>"""

    @staticmethod
    def generate_speak_xml(message: str, voice: str = "WOMAN", language: str = "en-US", loop: int = 1) -> str:
        """
        Generates canonical VobizXML that converts text to speech and terminates the call.
        """
        escaped_msg = xml.sax.saxutils.escape(str(message).strip())
        loop_cnt = max(1, int(loop or 1))
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="{voice}" language="{language}" loop="{loop_cnt}">{escaped_msg}</Speak>
    <Hangup/>
</Response>"""

