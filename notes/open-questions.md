
# Open Questions

## Open

- 10 vs 20s audio blocks? (considerations: gpu util, queue time, pbar jumping) (dia puts sweetspot regarding quality at [[5s, 20s]](https://github.com/nari-labs/dia?tab=readme-ov-file#generation-guidelines))

## Answered

- How can we calculate (do we need to approximate) the lenght of generated audio? (e.g. for large texts/docs)
  - -> approximate by number of tokens x average token length
- How will we make the progressbar be able to jump through the audio? Index by blocks?
  - -> yes, index by blocks. pbar: smooth progress animation between blocks 
- How to play/pause? Can the backend do it? Or does frontend just resubmit stuff? Caching? Caching specific text blocks?
  - -> play/pause: frontend just resubmits stuff, cache blocks
- How to split text into blocks? (per 10s or 20s)
    - paragraph -> spaCy sentence boundaries -> if still too big, hard split at nearest whitespace within +-5 % of of MAX_CHARS, else force-split.
