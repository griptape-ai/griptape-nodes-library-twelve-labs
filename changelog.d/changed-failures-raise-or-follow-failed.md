- **Breaking:** A TwelveLabs generation that fails, times out, or returns a result without the
  expected ID now raises on the node, or follows its `Failed` output when that is wired. It used to
  set the status text and end the run as if it had finished. Wire `Failed` to keep the old flow.
  A missing `GT_CLOUD_API_KEY` stops the node before it starts, so `Failed` is not followed for it.
  [#5](https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/issues/5)
