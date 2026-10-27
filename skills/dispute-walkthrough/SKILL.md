---
name: dispute-walkthrough
description: Walk a person through one credit-report dispute with PrivacyOps, from gathering facts to following up. Covers what to gather, which letter template to use, how to send it by certified mail, when to follow up, and how to log each step with the tools. Use when the user wants to dispute an item on a credit report, asks how to write or send a dispute letter, or asks what to do after an agency or a company answers.
license: MIT
source: https://github.com/seayniclabs/privacyops
author: Seaynic Labs
---

# Dispute walkthrough

**This is not legal advice.** The process tracks and drafts. It does not decide whether an item is wrong, whether the law gives the person a claim, or what a court would do. No lawyer has reviewed the templates. For a specific case, the person should ask a lawyer or a consumer-protection agency.

Never ask for, or accept in the chat, a Social Security number, a full account number, or a password. Describe an account in words instead, for example "credit card, late payment reported for March 2026".

## 1. Gather the facts

Ask for these in small groups, not all at once:

- The item in plain words: who reported it, what it says, and what it should say.
- The dates that matter: when the account activity happened, the date on the report, and the date of any payment.
- The reason the item is wrong, in one or two sentences. The letter needs this.
- Copies of supporting documents: payment confirmations, statements, letters, court records. Copies only. Originals stay with the person.
- Which report shows the item, if the person has one. Each agency's report can show different items.

If the person has no report in hand, record what they know and continue.

## 2. Choose the route

| Route | Recipient | Template (`letters_generate`) |
|---|---|---|
| The item is on a report from a consumer reporting agency (Equifax, Experian, TransUnion, or another agency) | The agency | `cra_dispute` |
| The person wants the company that reported the item to check it directly | That company (the furnisher) | `furnisher_dispute` |

Start with the agency. Send the company a direct dispute when the agency's answer is not enough or when the company is the one that can correct the item.

## 3. Create the record

Call `disputes_create`:

- `party_type`: `consumer_reporting_agency` or `furnisher`
- `party_name`: the agency or company name, as the person wrote it
- `item_description`: the item in plain words, with no account numbers
- `reason`: the reason from step 1
- `status`: `draft`

Keep the `id` from the reply. Every later step uses it.

## 4. Check the mailing address

Call `letters_templates`. It lists the agencies, and marks an address as checked only when the agency's own site showed it on the check date. For an agency without a checked address, tell the person to copy the address from that agency's website and write it on the letter by hand. The tool does not check it.

## 5. Write the letter

Call `letters_generate`:

- `template`: from step 2
- `item_description` and `reason`: from step 1
- `agency_key` (`equifax`, `experian` or `transunion`) for an agency, or `recipient_name` and `recipient_address` for a company
- `dispute_id`: the `id` from step 3, so the letter attaches to the record

The tool saves a text file and returns its `path` and `text`. Show the person the text. Then tell them:

- Fill in the bracketed placeholders by hand on the printed copy: `[YOUR FULL NAME]`, `[YOUR ADDRESS]`, `[YOUR SIGNATURE]`, the enclosure line, and any identifying number the recipient requires.
- Add a Social Security number only when the recipient's written instructions require it.
- Keep the not-legal-advice footer on the letter. It is part of the record.

## 6. Send it by certified mail

Tell the person to:

1. Print the letter, sign it, and add copies of the supporting documents.
2. Send it by USPS Certified Mail with a return receipt. The receipt gives the mailing date and proof of delivery.
3. Keep the receipt, the tracking page, a copy of the letter, and copies of each enclosure in one folder.

For an online dispute, use the agency's own dispute form and save the confirmation page. The submission date is the sent date.

Then call `disputes_update` with `status` set to `sent` and `sent_date` set to the mailing date on the receipt. For an online dispute, use the submission date.

## 7. Track the deadline

Call `disputes_deadlines` each time the person returns to the dispute, and at least once a week while any dispute is open. For each open dispute it returns:

- `due_date`: 30 days after the sent date, for an agency (15 U.S.C. 1681i(a)(1)(A))
- `days_remaining` and `overdue`
- `next_action`
- `unknowns`: facts the tool cannot know. Read them to the person word for word.

Explain the point people miss: the 30 days start when the agency receives the letter, not when it is mailed. The real deadline is the same or later than `due_date`.

## 8. When the answer arrives

Call `disputes_update` with `status` set to `response_received` and a `note` that states what came back and when. Keep the envelope or the email.

- **The item was corrected or deleted:** set `status` to `resolved` with a note that says what changed. Ask the person to check their credit report to confirm the change.
- **The item stayed the same:** read the stated reason with the person and record it in a note. Decide together whether to send a new dispute with new evidence, or a direct dispute to the company with `furnisher_dispute`.
- **The answer is unclear or incomplete:** record the exact wording in a note and leave the status as it is.

## 9. Follow up

When nothing arrives by `due_date`, the person sends a short written follow-up. PrivacyOps has no follow-up template, so write it by hand or draft it in this shape:

- The person's name and address placeholders, the date, and the agency or company.
- The original dispute: the date sent, the item in plain words, and the certified mail number.
- The statement that the 30-day period has passed with no written result.
- A request for the written result of the reinvestigation.

Send it by certified mail again. Then log it: call `disputes_update` with a `note` such as "Follow-up sent 2026-11-30 by certified mail." Keep the status as `sent`.

If the item is still disputed after the deadline, call `disputes_deadlines` again. It shows a 45-day date only for an agency, and only when the person sent relevant information in the first 30 days. Do not assume that extension applies.

## 10. Close out, and know when to get help

- Set `closed` when the person has the answer and nothing more to do.
- Keep the record. A delete needs the person's approval and does not remove letter files.
- Tell the person to get help from a lawyer or a consumer-protection agency when the company or agency does not answer after a written follow-up, a debt collector is involved, a lawsuit has been filed, or the person does not know what the law gives them. Consumer complaints can go to the Consumer Financial Protection Bureau (consumerfinance.gov) or to the state attorney general's consumer office.
