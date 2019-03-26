pipeline {

    agent { label "coverage-worker" }

    stages {
        stage('Run Tests') {
            agent { label "jenkins-worker" }
            environment {
                SHARD = 1
                TEST_SUITE = 'lms-unit'
            }
            steps {
                ansiColor('gnome-terminal') {
                    sshagent(credentials: ['jenkins-worker'], ignoreMissing: true) {
                        checkout changelog: false, poll: false, scm: [$class: 'GitSCM', branches: [[name: '${sha1}']],
                            doGenerateSubmoduleConfigurations: false, extensions: [], submoduleCfg: [],
                            userRemoteConfigs: [[credentialsId: 'jenkins-worker',
                            refspec: '+refs/heads/*:refs/remotes/origin/* +refs/pull/*:refs/remotes/origin/pr/*',
                            url: 'git@github.com:Edraak/edraak-platform.git']]]
                        stash includes: 'reports/**/*coverage*', name: "${TEST_SUITE}-${SHARD}-reports"
                    }
                }
           }

            post {
                always {
                    archiveArtifacts allowEmptyArchive: true, artifacts: 'reports/**/*,test_root/log/**/*.log,**/nosetests.xml,stdout/*.log,*.log'
                    junit '**/nosetests.xml'
                }
            }
        }
    }
}
