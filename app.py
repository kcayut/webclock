"""Compatibility entry point for existing systemd and Docker installations."""
import sys
from webclock import app as implementation

if __name__ == '__main__':
    implementation.main()
else:
    sys.modules[__name__] = implementation
