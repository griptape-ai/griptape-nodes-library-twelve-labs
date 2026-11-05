# Changelog

All notable changes to the TwelveLabs Nodes Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/), and each version is
the `library_version` in `twelvelabs_nodes_library/griptape_nodes_library.json`.
**Breaking** marks a change that can stop a saved workflow from working without edits.

## [Unreleased]

<!-- Entries go in changelog.d/, one file each. See changelog.d/README.md. -->

## [0.2.0] - 2026-11-06

### Changed

- **Breaking:** TwelveLabs Nodes Library requires engine 0.105.0 or later. Update the engine before
  updating the library.
  [#5](https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/issues/5)
- **Breaking:** A TwelveLabs generation that fails, times out, or returns a result without the
  expected ID now raises on the node, or follows its `Failed` output when that is wired. It used to
  set the status text and end the run as if it had finished. Wire `Failed` to keep the old flow.
  A missing `GT_CLOUD_API_KEY` stops the node before it starts, so `Failed` is not followed for it.
  [#5](https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/issues/5)
- TwelveLabs nodes report failures as structured node errors. A missing or refused
  `GT_CLOUD_API_KEY` links to Settings, and an API failure shows Griptape Cloud's own message with
  the status code, request ID and response under "More info". A missing key is reported on its own
  when a node runs, and a missing input names the parameter by its label.
  [#5](https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/issues/5)

[Unreleased]: https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/compare/527e66489b35fef71b47e76381f8123481cbd44f...v0.2.0
