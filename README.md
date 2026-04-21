# Sun SL Repository

Kodi 21 (Omega) addon repository by [sun250sw-alt](https://github.com/sun250sw-alt).

## Addons

| Addon | Version | Description |
|---|---|---|
| **Subtitle Translator** | 1.1.0 | Translate subtitles via Gemini AI or Google Translate from the Download Subtitles menu |

---

## Install Repository in Kodi

### Step 1 — Enable Unknown Sources
Settings → System → Add-ons → Unknown Sources → ON

### Step 2 — Add source
Settings → File Manager → Add source → enter:
```
https://raw.githubusercontent.com/sun250sw-alt/Sun_SL_Repo/main
```
Name it: `Sun SL Repo` → OK

### Step 3 — Install repository addon
Settings → Add-ons → Install from ZIP file → Sun SL Repo →
`repository.sun_sl_repo` → `repository.sun_sl_repo-1.0.0.zip`

Wait for **Repository installed** notification.

### Step 4 — Install Subtitle Translator
Settings → Add-ons → Install from repository → **Sun SL Repository** →
Subtitles → **Subtitle Translator** → Install

---

## Using Subtitle Translator

1. Play a video in Kodi
2. Press **T** or open OSD → Subtitles → Download Subtitles
3. Select **Subtitle Translator** from the left sidebar
4. Browse for your SRT or ZIP subtitle file
5. Select target language (remembers last choice)
6. Select timing adjustment if needed
7. Translation runs and subtitle loads automatically

---

## Gemini AI Setup (Optional)

Gemini AI gives more natural, story-aware translations compared to Google Translate. It's free with a Google account.

### Get your free API key:
1. Go to **aistudio.google.com**
2. Sign in with your Google account
3. Click **Get API Key** → **Create API Key**
4. Copy the key

### Add key to addon:
1. Open Download Subtitles in Kodi
2. Tap **Gemini API Key [Not set]** in the menu
3. Paste your key using the on-screen keyboard
4. Tap **Gemini Model** to choose your preferred model

### Free tier limits (resets daily at midnight Pacific Time):

| Model | Requests/day | ~Movies/day |
|---|---|---|
| Gemini 2.5 Flash *(recommended)* | 250 | ~10 |
| Gemini 2.5 Flash-Lite | 1000 | ~43 |
| Gemini 2.5 Pro | 100 | ~4 |

If the daily limit is reached, the addon automatically falls back to Google Translate.

---

## For developers — updating the repo

After changing any addon:
```bash
python3 _generate.py
```
Then commit and push all changes to GitHub.

---

## License
GPL-2.0
