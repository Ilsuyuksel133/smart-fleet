output "instance_id" {
  description = "ID of the EC2 instance."
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Public IP of the EC2 instance."
  value       = aws_instance.app.public_ip
}

output "api_url" {
  description = "Swagger UI of the API."
  value       = "http://${aws_instance.app.public_ip}:8000/docs"
}

output "grafana_url" {
  description = "Grafana dashboard."
  value       = "http://${aws_instance.app.public_ip}:3000"
}

output "security_group_id" {
  description = "ID of the application security group."
  value       = aws_security_group.app.id
}
