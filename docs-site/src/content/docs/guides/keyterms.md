---
title: Keyterm boosting
description: Bias recognition toward your domain vocabulary.
---

Product names, drug names, jargon — the words that matter most are the ones
generic models miss. Pass them as `keyterms` and the gateway translates to
each vendor's biasing mechanism (phrase lists, keyword boosts, keyterm
prompts):

```text
wss://api.speechrouter.ai/v1/listen?model=deepgram/nova-3&keyterms=SpeechRouter,Soniox,BYOK
```

```ts
sr.listen({ model: 'deepgram/nova-3', keyterms: ['SpeechRouter', 'Soniox', 'BYOK'] })
```

Works on batch too (`-F keyterms=...`).

## Vendor limits

Each vendor caps its list differently (AssemblyAI 100 terms, Azure 500, …) —
the gateway forwards up to the vendor's cap. Models without any biasing
mechanism simply ignore the parameter; the [provider pages](/providers/) mark
support.

## Tips

- Boost **rare** terms only. Boosting common words hurts accuracy.
- Casing is preserved where the vendor honors it (`SpeechRouter`, not
  `speechrouter`).
- Need vendor-specific weighting knobs? Reach through with
  `provider_params` — e.g. Speechmatics `additional_vocab` with
  `sounds_like`, or AssemblyAI's `keyterms_prompt`.
