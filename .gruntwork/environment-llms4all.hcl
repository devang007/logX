// Pipelines environment config for the llms4all AWS account.
// Pipelines reads all .hcl files in .gruntwork/. Add a new file here to register a new environment.
// Docs: https://docs.gruntwork.io/2.0/docs/pipelines/configuration/settings

environment "llms4all" {
  // Defines the environment as matching all units under llms4all/.
  filter {
    paths = ["llms4all/*"]
  }

  authentication {
    // Pipelines assumes these IAM roles via OIDC. No static credentials needed.
    // plan role: read-only, used on PRs. apply role: write, used on merge to deploy branch.
    // Both roles are created by the bootstrap stack in _global/bootstrap/.
    aws_oidc {
      account_id         = "8455859417"
      plan_iam_role_arn  = "arn:aws:iam::8455859417:role/pipelines-plan"
      apply_iam_role_arn = "arn:aws:iam::8455859417:role/pipelines-apply"
    }
  }
}
