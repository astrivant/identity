# Attribution

The quality gate and its negative-path tests are adapted from
[1password-agent-broker](https://github.com/astrivant/1password-agent-broker/tree/b780273413b66104df6247165fc3bf976fba9ef0/scripts/ci)
under [Apache-2.0](../documentation/broker.LICENSE). The required producer set
matches Witful's workflow; optional publication jobs are excluded from the PR gate.

Coverage publication follows the artifact-branch pattern inspected in
[Polyad's pipeline](https://github.com/astrivant/polyad/blob/c446fa5f0dc8eaaec82b49e864e8ca86046c53d1/.github/workflows/ci.yml).
The publisher here uses the maintained GitHub SDK action and signed commit API;
it does not copy that pipeline's older unsigned Git publisher.
