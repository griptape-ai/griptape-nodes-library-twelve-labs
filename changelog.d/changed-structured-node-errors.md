- TwelveLabs nodes report failures as structured node errors. A missing or refused
  `GT_CLOUD_API_KEY` links to Settings, and an API failure shows Griptape Cloud's own message with
  the status code, request ID and response under "More info". A missing key is reported on its own
  when a node runs, and a missing input names the parameter by its label.
  [#5](https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/issues/5)
