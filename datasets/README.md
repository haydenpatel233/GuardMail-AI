# GuardMail AI — Kaggle Datasets

Place downloaded CSV files here. The app auto-loads them on startup to expand keyword detection.

## Files to download

### 1. `phishing_emails.csv`
- **Dataset:** Phishing Email Dataset (Phish No More)
- **URL:** https://www.kaggle.com/datasets/naserabdullahalam/phishing-email-dataset
- **Used for:** Expanding SCAM_KEYWORDS from real phishing email text
- **Required column:** `Email Text`

### 2. `spam_ham.csv`
- **Dataset:** 190K+ Spam / Ham Email Dataset
- **URL:** https://www.kaggle.com/datasets/meruvulikith/190k-spam-ham-email-dataset-for-classification
- **Used for:** Expanding SPAM_KEYWORDS from labeled spam emails
- **Required columns:** `text`, `label`

### 3. `malicious_urls.csv`
- **Dataset:** Malicious URLs Dataset
- **URL:** https://www.kaggle.com/datasets/sid321axn/malicious-urls-dataset
- **Used for:** Expanding DANGEROUS_URL_KEYWORDS from phishing/malware URL paths
- **Required columns:** `url`, `type`

## How to download

1. Create a free Kaggle account at kaggle.com
2. Go to each dataset URL above
3. Click **Download** → extract the CSV
4. Rename it to the filename listed above
5. Place it in this `datasets/` folder
6. Restart the app — keywords load automatically on startup
