# TwelveLabs Nodes Library

This repository contains six Griptape nodes for working with TwelveLabs through the Griptape Cloud proxy API.

The library is built around the core TwelveLabs workflow:

1. Create an `index`
2. Upload one or more video `assets`
3. Index those assets into TwelveLabs `videos`
4. Run `search` across an index or `analysis` against a specific video

## Terminology

The naming in the TwelveLabs API can be easy to mix up. In this library, the terms mean:

- `index`: A logical collection of videos. The index is configured up front with model families and modalities, and that configuration is fixed after creation.
- `asset`: A video file that has been uploaded to TwelveLabs, but is not necessarily processed for retrieval or analysis yet.
- `video`: The TwelveLabs video resource produced after an uploaded asset is indexed. This is the ID used for analysis.
- `search`: A query across the videos inside an index.
- `analysis`: A prompt against one specific indexed video.

## Common Behavior

All six nodes share the same backend pattern:

- They call the Griptape Cloud proxy API, not TwelveLabs directly.
- They require the `GT_CLOUD_API_KEY` secret to be configured in Griptape.
- They submit an async generation, poll until completion, then fetch the final result.
- Polling is configured for up to 10 minutes by default.

## Setup

To use these nodes in Griptape:

1. Add the library manifest at `twelvelabs_nodes_library/griptape_nodes_library.json`.
2. Ensure the `GT_CLOUD_API_KEY` secret is set.
3. Drag nodes to your workflow canvas and create connections.

The library metadata registers `GT_CLOUD_API_KEY` as the required secret for this package.

## Node Overview

There are two main ways to use the library.

### Option 1: One-node ingest flow

Use `TwelveLabs Ingest Videos` when you want one node to:

1. create an index
2. upload one or more videos
3. index each uploaded asset

Outputs:

- `index_id`
- `asset_ids`
- `video_ids`

### Option 2: Composed flow

Use the nodes individually when you want more control:

1. `TwelveLabs Create Index`
2. `TwelveLabs Upload Asset`
3. `TwelveLabs Index Asset`
4. `TwelveLabs Search Index` or `TwelveLabs Analyze Video`

## Recommended Data Flow

### Search-oriented flow

`Create Index` -> `Upload Asset` -> `Index Asset` -> `Search Index`

### Video-specific analysis flow

`Create Index` -> `Upload Asset` -> `Index Asset` -> `Analyze Video`

### Batch ingest flow

`Ingest Videos` -> `Search Index` or `Analyze Video`

## Node Reference

### TwelveLabs Ingest Videos

Display name: `TwelveLabs Ingest Videos`

Purpose:
Create a new TwelveLabs index, upload one or more videos, then index each uploaded asset in sequence.

Inputs:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `marengo_model_name` | string | `marengo3.0` | Optional model family for search/classification. Allowed values: `""`, `marengo3.0`, `marengo2.7`. |
| `pegasus_model_name` | string | `pegasus1.2` | Optional generative model family. Allowed values: `""`, `pegasus1.2`. |
| `visual` | boolean | `true` | Include visual frames in model analysis. |
| `audio` | boolean | `true` | Include audio signals in model analysis. |
| `addons_csv` | string | empty | Optional comma-separated addons such as `thumbnail`. Requires Marengo to be enabled. |
| `enable_video_stream` | boolean | `false` | Passed to the asset indexing step. |
| `videos` | list | `[]` | Accepts one or more video inputs. The node accepts video artifacts, URLs, paths, strings, and lists. Each item is uploaded and then indexed. |

Outputs:

| Parameter | Type | Notes |
| --- | --- | --- |
| `index_id` | string | The created TwelveLabs index ID. |
| `asset_ids` | list[string] | Uploaded asset IDs, one per video. |
| `video_ids` | list[string] | Indexed TwelveLabs video IDs, one per uploaded asset. |
| `provider_response` | dict | Aggregate payload with `create_index`, `uploads`, and `indexes`. |

Behavior details:

- The node creates the index first, then uploads videos sequentially, then indexes assets sequentially.
- Index names are generated automatically as `gt-index-YYYYMMDD-xxxxxxxx`. The name is not user-configurable in the node.
- If a video input is already a public `http` or `https` URL and does not point to `localhost`, the node passes it through as-is.
- Otherwise, the node stages the video to a public URL before upload.
- Dynamic child outputs are created for the individual `asset_ids` and `video_ids`.

Validation rules:

- At least one of `marengo_model_name` or `pegasus_model_name` must be enabled.
- At least one of `visual` or `audio` must be enabled.
- `addons_csv` requires a Marengo model.
- At least one video is required.

Use this node when:

- you want the fastest path from raw video inputs to searchable/analyzable TwelveLabs videos
- you do not need to reuse an existing index

### TwelveLabs Create Index

Display name: `TwelveLabs Create Index`

Purpose:
Create a TwelveLabs index and return its ID.

Inputs:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `marengo_model_name` | string | `marengo3.0` | Optional model family for search/classification. Allowed values: `""`, `marengo3.0`, `marengo2.7`. |
| `pegasus_model_name` | string | `pegasus1.2` | Optional generative model family. Allowed values: `""`, `pegasus1.2`. |
| `visual` | boolean | `true` | Include visual frames in the configured model options. |
| `audio` | boolean | `true` | Include audio in the configured model options. |
| `addons_csv` | string | empty | Optional comma-separated addons. Requires Marengo. |

Outputs:

| Parameter | Type | Notes |
| --- | --- | --- |
| `index_id` | string | The created index ID. |
| `provider_response` | dict | Raw proxy result payload. |
| `generation_id` | string | Proxy generation ID. |

Behavior details:

- Model configuration is fixed after the index is created.
- The node auto-generates an index name internally to avoid collisions.
- The request payload includes only the model families that are enabled.

Validation rules:

- At least one model must be enabled.
- At least one model option must be enabled.
- `addons_csv` requires Marengo.

Use this node when:

- you want to create an index once and then upload/index videos later
- you need explicit control over the workflow rather than using `Ingest Videos`

### TwelveLabs Upload Asset

Display name: `TwelveLabs Upload Asset`

Purpose:
Upload a video into an existing TwelveLabs index and return the uploaded asset ID.

Inputs:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `index_id` | string | empty | Required. Existing TwelveLabs index ID. |
| `video` | video artifact | empty | Video input to upload. Use this for Griptape video artifacts or local file-backed inputs. |
| `asset_url` | string | empty | Public URL to the video. Use this instead of `video`. |

Outputs:

| Parameter | Type | Notes |
| --- | --- | --- |
| `asset_id` | string | Uploaded TwelveLabs asset ID. |
| `provider_response` | dict | Raw proxy result payload. |
| `generation_id` | string | Proxy generation ID. |

Behavior details:

- Exactly one of `video` or `asset_url` must be provided.
- If `video` is used, the node stages it to a public URL before submitting it to TwelveLabs.
- The node cleans up the staged artifact after the run.
- The node extracts the returned asset ID from either the top-level `_id` field or `assets[0]._id`.

Validation rules:

- `index_id` is required.
- Provide either `video` or `asset_url`, not both.
- One of `video` or `asset_url` is required.

Use this node when:

- you already have an index
- you want to upload now and index later

### TwelveLabs Index Asset

Display name: `TwelveLabs Index Asset`

Purpose:
Convert a previously uploaded asset into an indexed TwelveLabs video resource.

Inputs:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `index_id` | string | empty | Required. Existing TwelveLabs index ID. |
| `asset_id` | string | empty | Required. Uploaded asset ID to index. |
| `enable_video_stream` | boolean | `false` | Enables video stream for the indexed asset. |

Outputs:

| Parameter | Type | Notes |
| --- | --- | --- |
| `video_id` | string | Primary indexed TwelveLabs video ID. |
| `video_ids` | list[string] | Compatibility output for payloads that return multiple indexed IDs. |
| `provider_response` | dict | Raw proxy result payload. |
| `generation_id` | string | Proxy generation ID. |

Behavior details:

- In the usual case, one uploaded asset yields one `video_id`.
- The node also exposes `video_ids` because the proxy result may contain `indexed_asset_ids`.
- The parser prefers the top-level `_id` and falls back to the first valid ID in `indexed_asset_ids`.

Validation rules:

- `index_id` is required.
- `asset_id` is required.

Use this node when:

- you want a clear split between upload and indexing
- you need the TwelveLabs `video_id` for downstream analysis

### TwelveLabs Search Index

Display name: `TwelveLabs Search Index`

Purpose:
Search across the videos in a TwelveLabs index using a text query.

Inputs:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `index_id` | string | empty | Required. Existing TwelveLabs index ID. |
| `query_text` | string | empty | Required. Search prompt or description of what to find. |
| `search_options_csv` | string | `visual,conversation` | Comma-separated search options. The node converts this to a list before submission. |
| `page_limit` | integer | `10` | Maximum results to return. Range: `1` to `100`. |

Outputs:

| Parameter | Type | Notes |
| --- | --- | --- |
| `search_results` | dict | Raw search response payload from the proxy. |
| `result_count` | integer | Count of items in the top-level `data` array. |
| `provider_response` | dict | Same raw proxy result payload. |
| `generation_id` | string | Proxy generation ID. |

Behavior details:

- This node returns the raw search payload, not a flattened text-only summary.
- If you need a text output, read from `search_results` or feed the payload into downstream formatting logic.
- The node considers the run successful as long as the request completes; `result_count` may still be `0`.

Validation rules:

- `index_id` is required.
- `query_text` is required.
- `search_options_csv` must not be empty.

Use this node when:

- you want retrieval across all videos in an index
- you are building a flow that post-processes structured search results

### TwelveLabs Analyze Video

Display name: `TwelveLabs Analyze Video`

Purpose:
Run open-ended analysis against one indexed TwelveLabs video.

Inputs:

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `video_id` | string | empty | Required. Indexed TwelveLabs video ID. |
| `prompt` | string | empty | Required. The analysis prompt for that specific video. |
| `temperature` | float | `0.2` | Sampling temperature. Range: `0.0` to `1.0`. |
| `max_tokens` | integer | `1024` | Maximum output tokens. Range: `1` to `4096`. |

Outputs:

| Parameter | Type | Notes |
| --- | --- | --- |
| `analysis_result` | dict | Raw analysis response payload. |
| `analysis_text` | string | Best-effort extracted text from the response. |
| `provider_response` | dict | Same raw proxy result payload. |
| `generation_id` | string | Proxy generation ID. |

Behavior details:

- This is a video-level operation, not an index-level search.
- The node tries to extract readable text from common response shapes such as `text`, `analysis`, `summary`, `result`, `output`, `content`, `choices[0].message.content`, or `choices[0].text`.
- If no text-like field is found, `analysis_text` falls back to a JSON-formatted string of the full result payload.

Validation rules:

- `video_id` is required.
- `prompt` is required.

Use this node when:

- you want a direct question answered about one particular video
- you want both a raw JSON payload and a convenient text field for downstream use

## Choosing the Right Node

- Use `Ingest Videos` when you want one node to go from raw video inputs to `video_ids`.
- Use `Create Index` when you need to create an index separately from ingestion.
- Use `Upload Asset` when the video exists but has not been uploaded yet.
- Use `Index Asset` when the asset exists but has not been processed into a TwelveLabs video.
- Use `Search Index` when you want retrieval across a collection of videos.
- Use `Analyze Video` when you want a prompt answered about a single indexed video.

## Practical Notes

- The most important ID transition in this library is `asset_id` -> `video_id`.
- `Search Index` works on `index_id`; `Analyze Video` works on `video_id`.
- Both `Create Index` and `Ingest Videos` create new indexes with auto-generated names.
- The implementation documents model configuration at index creation time as fixed after creation.
- `Search Index` currently exposes structured results, while `Analyze Video` exposes both structured results and extracted text.
