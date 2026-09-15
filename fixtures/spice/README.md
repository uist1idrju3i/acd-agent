# SPICE fixture

`gd1-power.ngspice-out.txt` is recorded from ngspice 45.2 in the locked tools
container
`ghcr.io/uist1idrju3i/acd-tools@sha256:f6183da561f22b8c80197af37c700665ed6e9d273b9d1267658e61a36577dc25`.
The host does not provide ngspice; this container execution is a reproducible
parser fixture only. The request declares a 3.3 V LED drive and open-drain
I2C release stimulus. The recorded GD1 measurements are approximately
1.480687 mA through R6 and 206 ns for each I2C 10--90% rise time. The fixture
is an estimate and does not produce authoritative Evidence.
