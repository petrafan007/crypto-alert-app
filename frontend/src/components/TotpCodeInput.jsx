import React, { forwardRef, useRef, useImperativeHandle, useEffect } from 'react';

import { sanitizeTotpCode } from '../utils/webullOrderEntry.mjs';

export { sanitizeTotpCode };

/** A consistent native TOTP field for password managers and platform OTP autofill. */
const TotpCodeInput = forwardRef(function TotpCodeInput(
  { onChange, id = 'twoFactorCode', name = 'totp', ...props },
  ref
) {
  const inputRef = useRef(null);
  useImperativeHandle(ref, () => inputRef.current);

  const syncValueFromNode = (node, originalEvent) => {
    if (!node) return;
    const raw = node.value;
    const sanitized = sanitizeTotpCode(raw);
    if (node.value !== sanitized) {
      node.value = sanitized;
    }
    onChange?.({
      ...(originalEvent || {}),
      target: node,
      currentTarget: node,
    });
  };

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;

    // Native listener intercepts password manager autofill (Bitwarden, 1Password, etc.)
    const handleNativeInput = (event) => {
      syncValueFromNode(node, event);
    };

    node.addEventListener('input', handleNativeInput);
    node.addEventListener('change', handleNativeInput);

    // Periodically sync if an extension injects .value directly without standard events
    const pollInterval = setInterval(() => {
      if (node && node.value && node.value !== props.value) {
        syncValueFromNode(node);
      }
    }, 250);

    return () => {
      node.removeEventListener('input', handleNativeInput);
      node.removeEventListener('change', handleNativeInput);
      clearInterval(pollInterval);
    };
  }, [onChange, props.value]);

  const handleChange = (event) => {
    const sanitized = sanitizeTotpCode(event.target.value);
    if (event.target.value !== sanitized) event.target.value = sanitized;
    onChange?.(event);
  };

  const handleClick = (event) => {
    props.onClick?.(event);
  };

  const handleFocus = (event) => {
    props.onFocus?.(event);
  };

  const handlePaste = (event) => {
    const text = event.clipboardData?.getData('text') || '';
    const sanitized = sanitizeTotpCode(text);
    if (sanitized) {
      event.preventDefault();
      if (inputRef.current) inputRef.current.value = sanitized;
      const syntheticEvent = {
        ...event,
        target: inputRef.current || event.target,
        currentTarget: inputRef.current || event.target,
      };
      if (syntheticEvent.target) syntheticEvent.target.value = sanitized;
      onChange?.(syntheticEvent);
    }
    props.onPaste?.(event);
  };

  const handleAnimationStart = (event) => {
    if (event.animationName && event.animationName.toLowerCase().includes('autofill')) {
      syncValueFromNode(inputRef.current, event);
    }
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
      data-bwautofill="totp"
      data-1p-ignore="false"
      {...props}
      ref={inputRef}
      onClick={handleClick}
      onFocus={handleFocus}
      onPaste={handlePaste}
      onChange={handleChange}
      onAnimationStart={handleAnimationStart}
    />
  );
});

export default TotpCodeInput;
