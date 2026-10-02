import assert from 'node:assert/strict';
import test from 'node:test';

import { reconcileDedicatedAIConfig } from './dedicatedAIConfig.mjs';

const savedConfig = {
  audit_hours: 6,
  ai_config: {
    primary: { provider: 'gemini', model: 'gemini-3.8-flash' },
    secondary: { provider: 'ollama', model: 'nemotron-3-ultra:cloud' },
    tertiary: { provider: 'ollama', model: 'lfm2-cpu:latest' },
    quaternary: { provider: 'ollama', model: 'unknown-model:latest' },
  },
};

test('preserves unavailable saved models instead of silently selecting another model', () => {
  const options = {
    gemini: [{ value: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash' }],
    ollama: [
      { value: 'gemma4:26b', label: 'gemma4:26b' },
      { value: 'nemotron-3-ultra:cloud', label: 'nemotron-3-ultra:cloud' },
    ],
  };
  const result = reconcileDedicatedAIConfig(savedConfig, options);

  assert.equal(result.ai_config.secondary.model, 'nemotron-3-ultra:cloud');
  assert.equal(result.ai_config.tertiary.model, 'lfm2-cpu:latest');
  assert.equal(result.ai_config.quaternary.model, 'unknown-model:latest');
  assert.equal(savedConfig.ai_config.tertiary.model, 'lfm2-cpu:latest');
  assert.equal(savedConfig.ai_config.quaternary.model, 'unknown-model:latest');
});

test('preserves saved models while provider discovery is unavailable', () => {
  const result = reconcileDedicatedAIConfig(savedConfig, { gemini: [], ollama: [] });
  assert.strictEqual(result, savedConfig);
});
