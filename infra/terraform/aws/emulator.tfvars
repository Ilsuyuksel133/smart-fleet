# Moto (lokal AWS emülatörü) ile test için. Gerçek AWS'ye bağlanmaz.
use_local_emulator = true
emulator_endpoint  = "http://localhost:5000"

# Belgeleme için ayrılmış örnek IP aralığı (RFC 5737), gerçek bir ağ değil
allowed_cidrs = ["203.0.113.0/24"]

image_tag = "sha-0000000"

# Moto'nun sağladığı sahte Ubuntu AMI'si (Moto'da Ubuntu 24.04 AMI'si yok)
ami_id = "ami-785db401"
