include "root" {
  path = find_in_parent_folders("root.hcl")
}

locals {
  tutorial_input = yamldecode(file(mark_as_read(find_in_parent_folders("tutorial-cloud-input.yml"))))
}

terraform {
  source = "https://github.com/gruntwork-io/terragrunt-scale-catalog.git//modules/aws/s3-bucket?ref=v1.13.1"
}

inputs = {
  name = "tgs-tutorial-${get_aws_account_id()}-5d41f879-${local.tutorial_input.bucket_label}"
}
