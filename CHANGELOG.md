# Changelog

PrivacyOps follows [semantic versioning](https://semver.org). Modules added after 0.1 ship switched off.

## 0.1.0 — unreleased

- First release as one bundle with two modules: `disputes` (track disputes with consumer reporting agencies and furnishers) and `letters` (dispute letters from fixed templates).
- `disputes`: create, list (filtered and paged), get, update (status, sent date, note, with history), and delete. Delete asks you first, or is pre-approved with `PRIVACYOPS_DISPUTES_ALLOW_DELETE=true`.
- `letters`: two fixed templates (a reinvestigation request to a consumer reporting agency; a direct dispute to a furnisher), written as text files in your data folder. Your name, address, signature and any identifying numbers are placeholders you fill in by hand.
- Data is stored locally in one JSON file, written atomically so one update never drops other records. The file is created with owner-only permissions.
- No model or API calls. No Social Security number field exists anywhere.
- `privacyops_modules` discovery tool: which modules are on, what each tool does, where your data is, and the not-legal-advice disclaimer.
- Every generated letter carries the disclaimer in its footer. The templates have not been reviewed by a lawyer.
- Every tool returns structured data with a published output schema. Errors read `privacyops.<module>.<code>: <message> Fix: <hint>`.
- Runs over stdio or streamable HTTP. Starts with no settings.
