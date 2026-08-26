# ADR-018: Cilium policy provides reversible quarantine

Status: Accepted

CloudWard labels one recorded pod and applies one recorded CiliumNetworkPolicy with explicit
egress deny. This is more precise and reversible than a namespace or cluster-wide deny-all.
Lifecycle persistence and active connectivity verification prevent Kubernetes object creation
from being mistaken for containment.
