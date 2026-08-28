import packageMetadata from '../package.json';

// Package metadata is the single source for both the release and footer. This
// prevents a release from shipping a stale hard-coded footer version.
export const APP_VERSION = packageMetadata.version;
export const APP_VERSION_TAG = `v${APP_VERSION}`;
