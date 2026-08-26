# ADR-023: GitHub writes are allowlisted review artifacts

Status: Accepted

Read repositories, issue repositories, and content-write paths use independent allowlists enforced
for every client operation. CloudWard may create a deduplicated issue or change one allowlisted
path on a new branch and open a draft pull request. It has no merge operation and does not directly
apply persistent production configuration. Repository protection and human review remain
authoritative.
