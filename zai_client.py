#!/usr/bin/env python3
"""
Z.AI Client wrapper for handling AI requests
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

try:
	# Prefer modern package layout
	from zai._client import ZaiClient  # type: ignore
	_ZAI_SDK_AVAILABLE = True
except Exception:
	try:
		# Fallback older layout
		from zai import ZaiClient  # type: ignore
		_ZAI_SDK_AVAILABLE = True
	except Exception:
		# SDK not available; we'll use HTTP fallback
		ZaiClient = None  # type: ignore
		_ZAI_SDK_AVAILABLE = False

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class ZAIClient:
	"""Wrapper for Z.AI API client with multi-endpoint and SDK-or-HTTP fallback"""
	
	def __init__(self, api_key: str, timeout_seconds: int | None = None):
		"""Initialize Z.AI client with API key and candidate endpoints"""
		self.api_key = api_key
		self.client = None
		
		# Candidate endpoints in order of priority:
		# 1. Custom ZAI_BASE_URL if set
		# 2. Standard Global Z.AI endpoint
		# 3. BigModel platform backbone endpoint
		# 4. Coding Plan endpoint (for users with GLM Coding Plan subscriptions)
		custom_url = os.getenv("ZAI_BASE_URL")
		if custom_url:
			self.candidate_endpoints = [custom_url.rstrip("/")]
		else:
			self.candidate_endpoints = [
				"https://api.z.ai/api/paas/v4",
				"https://open.bigmodel.cn/api/paas/v4",
				"https://api.z.ai/api/coding/paas/v4"
			]
		self.base_url = self.candidate_endpoints[0]
		self.timeout = timeout_seconds or int(os.getenv("ZAI_HTTP_TIMEOUT", "60"))
		
		# Prepare resilient HTTP session without swallowing 429 responses into Retry loops
		self.session = requests.Session()
		retries = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504], allowed_methods=["POST"])  # type: ignore
		self.session.mount("https://", HTTPAdapter(max_retries=retries))
		
		if _ZAI_SDK_AVAILABLE and ZaiClient is not None:
			try:
				self.client = ZaiClient(api_key=api_key)
			except Exception as error:
				logger.warning(f"ZAI SDK initialization failed, using HTTP fallback: {error}")
				self.client = None
	
	def _http_chat_completion(self, messages: List[Dict[str, Any]], model: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
		"""HTTP implementation compatible with OpenAI-style API with automatic endpoint discovery and rate limit backoff."""
		import time
		headers = {
			"Authorization": f"Bearer {self.api_key}",
			"Content-Type": "application/json",
		}
		payload = {
			"model": model,
			"messages": messages,
			"max_tokens": max_tokens,
			"temperature": temperature,
		}

		last_error = "Unknown error"
		endpoints_to_try = [self.base_url] + [ep for ep in self.candidate_endpoints if ep != self.base_url]

		for ep_idx, endpoint_base in enumerate(endpoints_to_try):
			endpoint = f"{endpoint_base}/chat/completions"
			try:
				resp = self.session.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
				if resp.status_code == 200:
					self.base_url = endpoint_base  # Pin the working endpoint
					data = resp.json()
					choices = data.get("choices", [])
					content = ""
					if choices:
						msg_obj = choices[0].get("message", {})
						content = msg_obj.get("content", "") or ""
						if not content and "reasoning_content" in msg_obj:
							content = msg_obj.get("reasoning_content", "") or ""
					usage = data.get("usage", {})
					return {
						'success': True,
						'content': content,
						'model': model,
						'usage': {
							'prompt_tokens': usage.get('prompt_tokens'),
							'completion_tokens': usage.get('completion_tokens'),
							'total_tokens': usage.get('total_tokens'),
						}
					}

				# Extract detailed error message from response body
				err_msg = f"{resp.status_code} {resp.reason}"
				err_code = None
				try:
					err_data = resp.json()
					if isinstance(err_data, dict):
						if "error" in err_data:
							err_obj = err_data["error"]
							if isinstance(err_obj, dict):
								err_code = err_obj.get("code")
								err_msg = err_obj.get("message") or err_obj.get("msg") or str(err_obj)
							else:
								err_msg = str(err_obj)
						elif "msg" in err_data:
							err_msg = err_data["msg"]
						elif "message" in err_data:
							err_msg = err_data["message"]
				except Exception:
					err_msg = resp.text[:300] or err_msg

				# Handle insufficient balance cleanly
				if str(err_code) == "1113" or "insufficient balance" in err_msg.lower() or "余额不足" in err_msg:
					err_msg = f"Insufficient Z.AI balance for {model}. Please recharge your Z.AI account or switch to a free model (glm-4.5-flash / glm-4.7-flash)."

				last_error = f"{endpoint_base}: {resp.status_code} - {err_msg}"
				logger.warning(f"Z.AI request to {endpoint} returned {resp.status_code}: {err_msg}")

				# If rate limited (1302) or overloaded (1305), pause briefly before trying next endpoint
				if resp.status_code == 429 and ep_idx < len(endpoints_to_try) - 1:
					time.sleep(2)

			except requests.exceptions.RequestException as req_err:
				last_error = f"{endpoint_base}: {req_err}"
				logger.warning(f"Z.AI request to {endpoint} failed: {req_err}")

		# If the requested flash model is globally overloaded (code 1305 / 429), try sibling flash model
		if model in ['glm-4.7-flash', 'glm-4.7-flashx'] and "429" in str(last_error) and ("overloaded" in str(last_error).lower() or "过大" in str(last_error)):
			logger.info("Z.AI glm-4.7-flash is overloaded upstream, falling back to glm-4.5-flash...")
			fallback_res = self._http_chat_completion(messages, 'glm-4.5-flash', max_tokens, temperature)
			if fallback_res.get('success'):
				return fallback_res

		return {
			'success': False,
			'error': last_error,
			'content': None
		}
	
	def chat_completion(self, messages: List[Dict[str, Any]], model: str, max_tokens: int = 1000, temperature: float = 0.7) -> Dict[str, Any]:
		"""
		Send chat completion request to Z.AI using multi-endpoint HTTP client.
		"""
		try:
			return self._http_chat_completion(messages, model, max_tokens, temperature)
		except Exception as e:
			logger.error(f"Z.AI API error: {e}")
			return {
				'success': False,
				'error': str(e),
				'content': None
			}
	
	def get_available_models(self):
		"""Get list of available models"""
		return list(self.available_models.keys())
	
	def get_model_info(self, model):
		"""Get information about a specific model"""
		model_info = {
			'glm-4.5': {
				'name': 'GLM-4.5',
				'description': 'High Performance, Strong Reasoning, More Versatile',
				'input_price': '$0.6 / MTok',
				'output_price': '$2.2 / MTok',
				'context': '128K'
			},
			'glm-4.5-x': {
				'name': 'GLM-4.5-X',
				'description': 'High Performance, Strong Reasoning, Ultra-Fast Response',
				'input_price': '$2.2 / MTok',
				'output_price': '$8.9 / MTok',
				'context': '128K'
			},
			'glm-4.5-air': {
				'name': 'GLM-4.5-Air',
				'description': 'Cost-Effective, Lightweight, High Performance',
				'input_price': '$0.2 / MTok',
				'output_price': '$1.1 / MTok',
				'context': '128K'
			},
			'glm-4.5-airx': {
				'name': 'GLM-4.5-AirX',
				'description': 'Lightweight, High Performance, Ultra-Fast Response',
				'input_price': '$1.1 / MTok',
				'output_price': '$4.5 / MTok',
				'context': '128K'
			},
			'glm-4.5-flash': {
				'name': 'GLM-4.5-Flash',
				'description': 'Lightweight, High Performance',
				'input_price': 'Free',
				'output_price': 'Free',
				'context': '128K'
			},
			'glm-4-32b-0414-128k': {
				'name': 'GLM-4-32B-0414-128K',
				'description': 'High intelligence at unmatched cost-efficiency',
				'input_price': '$0.1 / MTok',
				'output_price': '$0.1 / MTok',
				'context': '128K'
			}
		}
		return model_info.get(model, {})


def test_zai_client(api_key: str) -> bool:
	"""Test Z.AI client with a simple request"""
	try:
		client = ZAIClient(api_key)
		messages = [
			{"role": "system", "content": "You are a helpful assistant."},
			{"role": "user", "content": "Hello! Please respond with 'Z.AI is working!'"}
		]
		response = client.chat_completion(messages, model='glm-4.5-flash')
		if response['success']:
			print("✅ Z.AI client test successful!")
			print(f"Response: {response['content']}")
			return True
		else:
			print(f"❌ Z.AI client test failed: {response['error']}")
			return False
	except Exception as e:
		print(f"❌ Z.AI client test failed: {e}")
		return False

if __name__ == "__main__":
	import sys
	if len(sys.argv) > 1:
		api_key = sys.argv[1]
		test_zai_client(api_key)
	else:
		print("Usage: python zai_client.py <api_key>") 
def call_ai_with_web_search(*args, **kwargs):
    from services.ai_service import call_ai_with_web_search as _real_call
    return _real_call(*args, **kwargs)
