- TwelveLabs Create Index and TwelveLabs Ingest Videos no longer offer `pegasus1.2`, which
  TwelveLabs has sunset for indexing. Pegasus Model is hidden and empty by default, so new indexes
  use Marengo only, and Marengo Model can no longer be left empty. A saved workflow that selected `pegasus1.2` loads with Pegasus disabled and
  shows a notice asking you to save it.
  [#7](https://github.com/griptape-ai/griptape-nodes-library-twelve-labs/issues/7)
