#!groovy

def stepsForParallel = [:]
def ENABLE_BOK_CHOY = false
def RUN_ONLY_JS_UNIT_AND_COMMONLIB = true

stage('Prepare') {
  def makeNode = { suite, shard ->
    return {
      echo "I am ${suite}:${shard}, and the worker is yet to be started!"

      node('worker-ami') {
        timeout(time: 55, unit: 'MINUTES') {
          echo "Hi, it is me ${suite}:${shard} again, the worker just started!"

          git 'https://github.com/Edraak/jenkins-edx-platform.git'

          withEnv(["TEST_SUITE=${suite}", "SHARD=${shard}"]) {
            sh './scripts/all-tests.sh'
          }
        }

        archiveArtifacts 'reports/*, test_root/log/*'
      }
    }
  }

  def getSuites = {
    def suites = [
      [name: 'js-unit', 'shards': 1],
      [name: 'commonlib-unit', 'shards': 1],
    ]

    if (!RUN_ONLY_JS_UNIT_AND_COMMONLIB) {
      suites.addAll([
        [name: 'quality', 'shards': 1],
        [name: 'lms-unit', 'shards': 4],
        [name: 'cms-unit', 'shards': 1],
        [name: 'lms-acceptance', 'shards': 1],
        [name: 'cms-acceptance', 'shards': 1],
      ])
    }

    if (ENABLE_BOK_CHOY) {
      suites.add([name: 'bok-choy', 'shards': 9])
    }

    return suites
  }

  def buildParallelSteps = {
    def suites = getSuites()

    for (int suiteId=0; suiteId<suites.size(); suiteId++) {
      def suite = suites.get(suiteId)
      def name = suite['name']
      def shards = suite['shards']

      if (shards > 1) {
        for (int shardIndex=1; shardIndex<=shards; shardIndex++) {
          stepsForParallel["${name}_shard_${shardIndex}"] = makeNode(name, shardIndex)
        }
      } else {
        stepsForParallel["${name}_all"] = makeNode(name, 'all')
      }
    }
  }

  buildParallelSteps()
  echo 'Starting the build...'
}

stage('Test') {
  parallel stepsForParallel
}

stage('Done') {
  echo 'I am done, hurray!'
}
