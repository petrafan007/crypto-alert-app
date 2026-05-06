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
	"""Wrapper for Z.AI API client with SDK-or-HTTP fallback"""
	
	def __init__(self, api_key: str, timeout_seconds: int | None = None):
		"""Initialize Z.AI client with API key"""
		self.api_key = api_key
		self.client = None
		self.base_url = "https://api.z.ai/api/paas/v4"
		self.timeout = timeout_seconds or int(os.getenv("ZAI_HTTP_TIMEOUT", "60"))
		# Prepare resilient HTTP session
		self.session = requests.Session()
		retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["POST"])  # type: ignore
		self.session.mount("https://", HTTPAdapter(max_retries=retries))
		if _ZAI_SDK_AVAILABLE and ZaiClient is not None:
			try:
				self.client = ZaiClient(api_key=api_key)
			except Exception as error:
				logger.warning(f"ZAI SDK initialization failed, using HTTP fallback: {error}")
				self.client = None
	
	def _http_chat_completion(self, messages: List[Dict[str, Any]], model: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
		"""HTTP fallback implementation compatible with OpenAI-style API."""
		endpoint = f"{self.base_url}/chat/completions"
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
		resp = self.session.post(endpoint, json=payload, headers=headers, timeout=self.timeout)
		if not resp.ok:
			# Log detailed error information
			error_details = f"Z.AI API Error: {resp.status_code} - {resp.reason}"
			try:
				error_json = resp.json()
				error_details += f" - Response: {error_json}"
			except:
				error_details += f" - Text: {resp.text[:500]}"
			logger.error(error_details)
		resp.raise_for_status()
		data = resp.json()
		# Normalize to expected shape
		content = data["choices"][0]["message"]["content"]
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
	
	def chat_completion(self, messages: List[Dict[str, Any]], model: str, max_tokens: int = 1000, temperature: float = 0.7) -> Dict[str, Any]:
		"""
		Send chat completion request to Z.AI. Uses the model passed in; no hardcoded defaults.
		"""
		try:
			# Prefer SDK if available
			if self.client is not None:
				# Some SDKs don't expose timeout; rely on HTTP fallback if SDK errors
				response = self.client.chat.completions.create(
					model=model,
					messages=messages,
					max_tokens=max_tokens,
					temperature=temperature
				)
				content = response.choices[0].message.content
				return {
					'success': True,
					'content': content,
					'model': model,
					'usage': {
						'prompt_tokens': getattr(response.usage, 'prompt_tokens', None),
						'completion_tokens': getattr(response.usage, 'completion_tokens', None),
						'total_tokens': getattr(response.usage, 'total_tokens', None),
					}
				}
			# HTTP fallback
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
    """Stub for backward compatibility during modular refactor."""
    print("WARNING: call_ai_with_web_search is currently a stub.")
    return "AI Analysis temporarily unavailable.", None
