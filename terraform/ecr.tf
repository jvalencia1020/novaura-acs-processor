data "aws_ecr_repository" "processor_repository" {
  name = "novaura-acs-processor"
}

output "repository_url" {
  value = data.aws_ecr_repository.processor_repository.repository_url
} 