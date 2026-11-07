# Source provenance

The primary experiment uses the versioned source in this directory and the shared helpers in `../temporal_filter_study/`. Source hashes are recorded in `source_manifest.json`; input/archive hashes are recorded separately in `results/archive_inventory.csv`. Use the published branch containing these files for the primary6000-frame reproduction.

The earlier1800-frame study retains its original source manifest. Its `7764852` source checkpoint and `789bec9` results checkpoint were local commits. They identify historical states; they are not public checkout instructions. Their hashes have not been relabelled as a different commit. The original local Git history and raw archives remain on the validation host. Those recorded hashes can differ from current shared helpers, which now accept both approved durations and take a root argument. Current helpers still support the earlier archives, but the current checkout is not presented as the byte-identical historical source snapshot.

Historical live runners that require the pre-removal production pipeline point to the public baseline `e8372ce0f58528b585a5785a8fbb0bc2250165a3`. That baseline has the same production pipeline and runner source as the local pre-removal checkpoint. It does not contain the later study code/results and is not used to replace their historical source identifiers.

No experimental calendar date is included in the current protocol, results narrative or new capture manifests. Historical raw metadata stays local. Source fingerprints preserve what was measured; they do not claim the raw images are hosted in Git.
