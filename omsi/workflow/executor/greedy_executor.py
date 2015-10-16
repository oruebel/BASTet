"""
Module used to help with the execution of complex analyses workflows
"""
from omsi.workflow.executor.base import workflow_executor_base
from omsi.shared.run_info_data import run_info_dict
from omsi.shared.log import log_helper
from omsi.shared.analysis_data import data_dtypes
import omsi.shared.mpi_helper as mpi_helper


class greedy_executor(workflow_executor_base):
    """
    Execute a set of analysis objects and their dependencies

    :ivar run_info: The runtime information dictionary for the overall workflow
    :ivar mpi_comm: The MPI communicator to be used when running in parallel
    :ivar mpi_root: The MPI root rank when running in parallel

    Additional parameters:

    :param reduce_memory_usage: Boolean indicating whether we should reduce memory usage by pushing analysis
        data to file after an analysis has been completed. This reduces the amount of data we keep in memory
        but results in additional overhead for I/O and temporary disk storage.

    """
    def __init__(self, analysis_objects=None):
        """
        Initalize the workflow driver

        :param analysis_objects: A list of analysis objects to be executed
        """
        super(greedy_executor, self).__init__(analysis_objects)
        self.mpi_comm = mpi_helper.get_comm_world()
        self.mpi_root = 0
        self.add_parameter(name='reduce_memory_usage',
                           help='Reduce memory usage by pushing analyses to file each time they ' +
                                'complete, processing dependencies out-of-core.',
                           dtype=data_dtypes.bool_type,
                           required=False,
                           default=False)
        self.add_parameter(name='synchronize',
                           help='Place an MPI-barrier at the beginning of the exection of the workflow. ' +
                                'This can be useful when we require that all MPI ranks are fully initalized.',
                           dtype=data_dtypes.bool_type,
                           required=False,
                           default=False)

    def main(self):
        """
        Execute the analysis workflow
        """
        # Do the optional MPI barrier
        if self['synchronize']:
            mpi_helper.barrier(comm=self.mpi_comm)

        # Check if we have anything to do at all
        if len(self.get_analyses()) == 0:
            log_helper.info(__name__, "The workflow is empty", root=self.mpi_root, comm=self.mpi_comm)
            return

        # Add all dependencies to the workflow
        log_helper.debug(__name__, "Executing the workflow", root=self.mpi_root, comm=self.mpi_comm)
        log_helper.info(__name__, "Adding all dependencies", root=self.mpi_root, comm=self.mpi_comm)
        self.add_analysis_dependencies()

        # Execute the workflow in a greedy fashion (i.e., execute whichever analysis is ready and has not be run yet)
        log_helper.debug(__name__, "Running the analysis workflow", root=self.mpi_root, comm=self.mpi_comm)
        all_analyses = self.get_analyses()
        iterations = 0
        while True:
            # Run all analyses that are ready
            for analysis in all_analyses:
                if analysis.update_analysis and len(analysis.check_ready_to_execute()) == 0:
                    log_helper.debug(__name__, "Execute analysis: " + str(analysis),
                                     root=self.mpi_root, comm=self.mpi_comm)
                    analysis.execute()
                    if self['reduce_memory_usage']:
                        analysis.clear_and_restore()
            # Check if there is any other tasks that we need to execte now
            num_tasks = 0
            num_tasks_ready = 0
            for analysis in all_analyses:
                if analysis.update_analysis:
                    num_tasks += 1
                    if len(analysis.check_ready_to_execute()) == 0:
                        num_tasks_ready += 1
            if num_tasks == 0:
                log_helper.info(__name__, "Completed executing the workflow.", root=self.mpi_root, comm=self.mpi_comm)
                break
            if num_tasks > 0 and num_tasks_ready == 0:
                log_helper.warning(__name__, "Workflow could not be fully executed. " + str(num_tasks) +
                                   " remain in the queue but cannot be completed due to unresolved dependencies.",
                                   root=self.mpi_root, comm=self.mpi_comm)
            iterations += 1

        log_helper.log_var(__name__, iterations=iterations, level='DEBUG', root=self.mpi_root, comm=self.mpi_comm)
