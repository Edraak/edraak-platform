"""
Edraak's better rate limit backend.

The feature flag `EDRAAK_RATELIMIT_APP` enables this module on non-test environments.

This module depends on `ENABLE_MAX_FAILED_LOGIN_ATTEMPTS` feature for the student-based locks to be enabled.

Introduces three enhancements over the original edX ratelimited backend:

 - Edraak (ratelimit): Loosen up the limits on IP to allow more room of error for university students
                       since they usually connect from the same IP.
 - Edraak (ratelimit): Logs the IP-based ratelimit issues in the database.
 - Edraak (ratelimit): Shows an admin page for both user and IP based lock  and allow clearning those limit.
"""
