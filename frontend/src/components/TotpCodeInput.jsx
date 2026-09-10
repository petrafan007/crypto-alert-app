import React, { forwardRef } from 'react';

export const sanitizeTotpCode = (value) => String(value ?? '')
  .replace(/\D/g, '')
  .slice(0, 6);

/** A consistent native TOTP field for password managers and platform OTP autofill. */
const TotpCodeInput = forwardRef(function TotpCodeInput({ onChange, id = 'twoFactorCode', name = 'totp', ...props }, ref) {
  const handleChange = (event) => {
    const sanitized = sanitizeTotpCode(event.target.value);
    if (event.target.value !== sanitized) event.target.value = sanitized;
    onChange?.(event);
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
      onChange={handleChange}
    />
  );
});

export default TotpCodeInput;
