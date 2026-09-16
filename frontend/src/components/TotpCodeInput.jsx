import React, { forwardRef } from 'react';

import { sanitizeTotpCode } from '../utils/webullOrderEntry.mjs';

export { sanitizeTotpCode };

/** A consistent native TOTP field for password managers and platform OTP autofill. */
const TotpCodeInput = forwardRef(function TotpCodeInput({ onChange, id = 'twoFactorCode', name = 'totp', ...props }, ref) {
  const handleChange = (event) => {
    const sanitized = sanitizeTotpCode(event.target.value);
    if (event.target.value !== sanitized) event.target.value = sanitized;
    onChange?.(event);
  };

  const handleClick = (event) => {
    event.target.select?.();
    props.onClick?.(event);
  };

  const handleFocus = (event) => {
    event.target.select?.();
    props.onFocus?.(event);
  };

  const handlePaste = (event) => {
    const text = event.clipboardData?.getData('text') || '';
    const sanitized = sanitizeTotpCode(text);
    if (sanitized) {
      event.preventDefault();
      const syntheticEvent = {
        ...event,
        target: { ...event.target, value: sanitized, name: event.target.name || name },
      };
      if (event.target) event.target.value = sanitized;
      onChange?.(syntheticEvent);
    }
    props.onPaste?.(event);
  };

  return (
    <input
      id={id}
      name={name}
      type="text"
      inputMode="numeric"
      pattern="[0-9]*"
      maxLength={6}
      autoComplete="one-time-code"
      autoCapitalize="none"
      spellCheck={false}
      aria-label="Two-factor authentication code"
      {...props}
      ref={ref}
      onClick={handleClick}
      onFocus={handleFocus}
      onPaste={handlePaste}
      onChange={handleChange}
    />
  );
});

export default TotpCodeInput;
