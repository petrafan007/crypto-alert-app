import assert from 'node:assert/strict';
import test from 'node:test';

import { reconcileDedicatedAIConfig } from './dedicatedAIConfig.mjs';

const savedConfig = {
  audit_hours: 6,
  ai_config: {
    primary: { provider: 'gemini', model: 'gemini-3.8-flash' },
    secondary: { provider: 'ollama', model: 'nemotron-3-ultra:cloud' },
    tertiary: { provider: 'ollama', model: 'lfm2-cpu:latest' },
  },
};

test('replaces an unavailable saved model with the model rendered by the select', () => {
  const options = {
    gemini: [{ value: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' }],
    ollama: [
      { value: 'gemma4:26b', label: 'gemma4:26b' },
      { value: 'nemotron-3-ultra:cloud', label: 'nemotron-3-ultra:cloud' },
    ],
  };
  const result = reconcileDedicatedAIConfig(savedConfig, options);

  assert.equal(result.ai_config.secondary.model, 'nemotron-3-ultra:cloud');
  assert.equal(result.ai_config.tertiary.model, 'gemma4:26b');
  assert.equal(savedConfig.ai_config.tertiary.model, 'lfm2-cpu:latest');
});

test('preserves saved models while provider discovery is unavailable', () => {
  const result = reconcileDedicatedAIConfig(savedConfig, { gemini: [], ollama: [] });
  assert.strictEqual(result, savedConfig);
});
