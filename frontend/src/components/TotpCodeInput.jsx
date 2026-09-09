import React, { forwardRef } from 'react';

export const sanitizeTotpCode = (value) => String(value ?? '')
  .replace(/\D/g, '')
  .slice(0, 6);

/** A consistent native TOTP field for password managers and platform OTP autofill. */
const TotpCodeInput = forwardRef(function TotpCodeInput({ onChange, ...props }, ref) {
  const handleChange = (event) => {
    const sanitized = sanitizeTotpCode(event.target.value);
    if (event.target.value !== sanitized) event.target.value = sanitized;
    onChange?.(event);
  };

  return (
    <input
      {...props}
      ref={ref}
      type="text"
      name="one-time-code"
      inputMode="numeric"
      pattern="[0-9]*"
      maxLength={6}
      autoComplete="one-time-code"
      autoCapitalize="none"
      spellCheck={false}
      onChange={handleChange}
    />
  );
});

export default TotpCodeInput;
