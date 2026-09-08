const DEDICATED_AI_TIERS = ['primary', 'secondary', 'tertiary'];

const optionValue = (option) => (
  option && typeof option === 'object' ? option.value : option
);

/**
 * Keep dedicated-cascade form state aligned with the models a select can show.
 * If model discovery is unavailable, preserve the saved value instead of
 * silently replacing it with a fallback that has not been verified.
 */
export const reconcileDedicatedAIConfig = (config, modelOptions) => {
  if (!config?.ai_config || !modelOptions) return config;

  let nextAIConfig = config.ai_config;
  let changed = false;

  DEDICATED_AI_TIERS.forEach((tierName) => {
    const tier = config.ai_config[tierName];
    if (!tier?.provider) return;
    const options = modelOptions[tier.provider];
    if (!Array.isArray(options) || options.length === 0) return;

    const availableModels = options.map(optionValue).filter(Boolean);
    if (!availableModels.length || availableModels.includes(tier.model)) return;

    if (!changed) nextAIConfig = { ...config.ai_config };
    nextAIConfig[tierName] = { ...tier, model: availableModels[0] };
    changed = true;
  });

  return changed ? { ...config, ai_config: nextAIConfig } : config;
};
