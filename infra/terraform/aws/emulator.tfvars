# For testing against Moto (local AWS emulator). Never connects to real AWS.
use_local_emulator = true
emulator_endpoint  = "http://localhost:5000"

# IP range reserved for documentation (RFC 5737), not a real network
allowed_cidrs = ["203.0.113.0/24"]

image_tag = "sha-0000000"

# Fake Ubuntu AMI provided by Moto (Moto has no Ubuntu 24.04 AMI)
ami_id = "ami-785db401"
