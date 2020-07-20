pipeline {
  agent none

  parameters {
    string(name: 'GIT_COMMIT', defaultValue: 'master', description: 'Commit SHA or origin branch to deploy')
  }

  stages {
    stage('build') {
      agent {
        kubernetes {
        defaultContainer 'jnlp'
        yaml """
            apiVersion: v1
            kind: Pod
            metadata:
              labels:
                job: ${env.JOB_NAME}
                job_id: ${env.BUILD_NUMBER}
            spec:
              nodeSelector:
                role: worker
              containers:
              - name: builder
                image: gcr.io/kaniko-project/executor:debug
                imagePullPolicy: Always
                command:
                - cat
                tty: true
                volumeMounts:
                - name: jenkins-docker-cfg
                  mountPath: /kaniko/.docker
              volumes:
              - name: jenkins-docker-cfg
                configMap:
                  name: docker-config
                  items:
                  - key: config.json
                    path: config.json
        """
        }
      }
      steps {
        checkout([
            $class: 'GitSCM',
            branches: [[name: params.GIT_COMMIT]],
            userRemoteConfigs: [[url: 'https://github.com/uktrade/data-workspace.git']]
        ])
        script {
          pullRequestNumber = sh(
              script: "git log -1 --pretty=%B | grep 'Merge pull request' | cut -d ' ' -f 4 | tr -cd '[[:digit:]]'",
              returnStdout: true
          ).trim()
          currentBuild.displayName = "#${env.BUILD_ID} - PR #${pullRequestNumber}"
        }
        script {
          withCredentials([string(credentialsId: 'SENTRY_PROJECT_RELEASES', variable: 'SENTRY_AUTH_TOKEN')]) {
            sh "docker run --rm -v $(pwd):/work -e SENTRY_AUTH_TOKEN -e SENTRY_ORG -e SENTRY_URL getsentry/sentry-cli:1 releases new -p data-workspace \"${params.GIT_COMMIT}\""
            sh "docker run --rm -v $(pwd):/work -e SENTRY_AUTH_TOKEN -e SENTRY_ORG -e SENTRY_URL getsentry/sentry-cli:1 releases set-commits --auto \"${params.GIT_COMMIT}\""
          }
        }
        lock("data-workspace-build-admin") {
          container(name: 'builder', shell: '/busybox/sh') {
            withEnv(['PATH+EXTRA=/busybox:/kaniko']) {
              sh """
                #!/busybox/sh
                /kaniko/executor --dockerfile ${env.WORKSPACE}/Dockerfile -c ${env.WORKSPACE} --destination=quay.io/uktrade/data-workspace:${params.GIT_COMMIT}
                """
            }
          }
        }
        script {
          withCredentials([string(credentialsId: 'SENTRY_PROJECT_RELEASES', variable: 'SENTRY_AUTH_TOKEN')]) {
            sh "docker run --rm -v $(pwd):/work -e SENTRY_AUTH_TOKEN -e SENTRY_ORG -e SENTRY_URL getsentry/sentry-cli:1 releases finalize \"${params.GIT_COMMIT}\""
          }
        }
      }
    }


    stage('release: dev') {
      steps {
        ecs_pipeline("analysisworkspace-dev", params.GIT_COMMIT)
      }
    }


    stage('release: staging') {
      when {
          expression {
              milestone label: "release-staging"
              input message: 'Deploy to staging?'
              return true
          }
          beforeAgent true
      }

      steps {
        ecs_pipeline("data-workspace-staging", params.GIT_COMMIT)
      }
    }


    stage('release: prod') {
      when {
          expression {
              milestone label: "release-prod"
              input message: 'Deploy to prod?'
              return true
          }
          beforeAgent true
      }

      steps {
        ecs_pipeline("jupyterhub", params.GIT_COMMIT)
      }
    }
  }
}

void ecs_pipeline(cluster, version) {
  lock("data-workspace-ecs-pipeline-${cluster}") {
    build job: "ecs-pipeline", parameters: [
        string(name: "Image", value: "quay.io/uktrade/data-workspace:${version}"),
        string(name: "Cluster", value: cluster),
        string(name: "Service", value: "${cluster}-admin"),
        string(name: "CredentialsId", value: "DATASCIENCE_ECS_DEPLOY")
    ]
  }
}
