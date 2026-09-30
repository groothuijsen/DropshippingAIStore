# Prompts: images (step 4)

## A. Shot plan (Anthropic, `LLM_MODEL_COPY`, temp 0.5, tool `submit_image_plan`)

Output: list of `ImageShot` (05 §3), at most the number of remaining image credits and at most 5.

### System
You plan product photography for an e-commerce page. You receive the page sections, the product facts and 1–4 reference photos of the real product. For each image slot used by the sections, write one image-generation prompt in English.

Rules:
1. The product must look exactly like the reference photos: same shape, colour, materials, logos, number of parts, proportions. Describe the product precisely in every prompt.
2. No text, labels, prices, badges or logos added to the image, except those physically on the product.
3. No recognisable real people, celebrities or public figures. If a person is needed, use hands only or a figure seen from behind or cropped at the shoulders; set `people_allowed=false` otherwise.
4. No before/after comparisons, no medical settings, no children.
5. Styles: `hero` = clean studio or brand-colour background; `lifestyle_*` = realistic home/car/daily-use scene fitting the persona; `detail_*` = macro of material or feature from the facts.
6. Aspect ratio: hero 4:5, lifestyle 16:9 or 4:5, detail 1:1.

### User
Sections: {{ sections_json }}
Facts: {{ facts_json }}
Brand palette: {{ palette_json }}
Reference image URLs: {{ reference_urls }}

## B. Generation (`gemini-3.1-flash-image` → `gemini-3-pro-image` → `gpt-image-2.5-sunburst`, see 05 §4.4)

- Send the prompt + the reference images as edit/reference input (image editing / subject reference), not just text.
- Define parameters in `apps/ai/images.py`: count = 1 per call; Gemini: `imageConfig.aspectRatio` and `imageConfig.imageSize` (`1K`/`2K`) — verify field names against the Vertex docs in T-040; OpenAI: `size` (both sides divisible by 16), `input_fidelity: "high"`; output PNG.
- Leave the provider's safety filters on; a refused image = skip slot.

## C. Fidelity check (Anthropic, `LLM_MODEL_CHECK`, temp 0, tool `submit_fidelity`)

### System
Compare the generated image with the reference photos of the real product. Answer only about the product itself, not the background. Return `same_product` (bool) and `issues` (list of short strings: e.g. "different colour", "extra button", "logo missing", "wrong proportions", "text added").

### User
Reference photos: [images]
Generated image: [image]

`same_product=false` or one of the issues "text added"/"logo missing"/"different colour" → reject.
