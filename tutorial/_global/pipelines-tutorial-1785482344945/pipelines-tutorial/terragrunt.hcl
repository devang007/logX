locals {
  tutorial_input = yamldecode(file(mark_as_read(find_in_parent_folders("tutorial-input.yml"))))
}

terraform {
  source = "https://github.com/gruntwork-io/terragrunt-scale-catalog.git//modules/null?ref=v1.13.1"
}

inputs = {
  message = try(local.tutorial_input.message, "default-message")
}
