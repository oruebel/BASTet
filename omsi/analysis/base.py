"""
Module specifying the base analysis API for integrating new analysis with the toolkit and the
OpenMSI science gateway.
"""


import time
import warnings
import weakref
import numpy as np

from omsi.dataformat.omsi_file.format import omsi_format_common
from omsi.dataformat.omsi_file.analysis import omsi_file_analysis
from omsi.dataformat.omsi_file.msidata import omsi_file_msidata
from omsi.analysis.analysis_data import analysis_data, parameter_data, analysis_dtypes
from omsi.shared.dependency_data import dependency_dict
import omsi.shared.mpi_helper as mpi_helper
from omsi.shared.run_info_data import run_info_dict


class AnalysisReadyError(Exception):
    """
    Custom exception used to indicate that an analysis is not ready to execute.
    """
    def __init__(self, value, params=None):
        """
        Initialize the AnalysisReadyError

        :param value: Error message string
        :param params: Optional list of dependent parameters that are not ready to be used.
        """
        self.value = value
        self.params = params
        message = unicode(self.value)
        if self.params is not None and len(self.params) > 0:
            message += " The following parameters are not ready: "
            for param in self.params:
                try:
                    message += " " + param['name']
                except KeyError:
                    pass
        super(AnalysisReadyError, self).__init__(repr(message))



class analysis_base(object):
    """
    Base class for omsi analysis functionality. The class provides a large set of functionality designed
    to facilitate storage of analysis data in the omsi HDF5 file format. The class also provides a set
    of functions to enable easy intergration of new analysis with the OpenMSI web-based viewer (see
    Viewer functions below for details).

    **Slicing:**

    This class supports basic slicing to access data stored in the main member variables. By
    default the data is retrieved from __data_list and the __getitem__(key) function. which implements
    the [..] operator, returns __data_list[key]['data']. The key is a string indicating the name of
    the parameter to be retrieved. If the key is not found in the __data_list then the function will
    try to retrieve the data from self.parameters list instead. By adding "parameter/key" or "dependency/key"
    one may also explicitly retrieve values from the parameters.

    **Instance Variables:**

    :ivar analysis_identifier: Define the name for the analysis used as key in search operations
    :ivar __data_list: Dictonary of analysis_data to be written to the HDF5 file. Derived classes
        need to add all data that should be saved for the analysis in the omsi HDF5 file to this dictionary.
        See omsi.analysis.analysis_data for details.
    :ivar parameters: List of parameter_data objects of all  analysis parameters
         (including those that may have dependencies).
    :ivar data_names: List of strings of all names of analysis output datasets. These are the
         target keys for __data_list.
    :ivar profile_time_and_usage: Boolean indicating whether we should profile the execute_analysis(...) function
        when called as part of the execute(...) function. The default value is false. Use the
        enable_time_and_usage_profiling(..) function to determine which profiling should be performed. The time_and
        _usage profile uses pythons cProfile (or Profile) to monitor how often and for how long particular parts
        of the analysis code executed.
    :ivar profile_memory: Boolean indicating whether we should monitor memory usage (line-by-line) when
        executing the execute_analysis(...) function. The default value is false. Use the
        enable_time_and_usage_profiling(..) function to determine which profiling should be performed.
    :ivar omsi_analysis_storage: List of omsi_file_analysis object where the analysis is stored. The list may be empty.
    :ivar mpi_comm: In case we are running with MPI, this is the MPI communicator used for runnign the analysis.
        Default is MPI.Comm_world/
    :ivar mpi_root: In case we are running with MPI, this is the root rank where data is collected to (e.g., runtime
        data and analysis results)


    **Execution Functions:**

    * ``execute`` : Then main function the user needs to call in order to execute the analysis
    * ``execute_analysis: This function needs to be implemented by child classes of `analysis_base` \
        to implement the specifics of executing the analysis.

    **I/O functions:**

    These functions can be optionally overwritten to control how the analysis data should be written/read
    from the omsi HDF5 file. Default implementations are provided here, which should be sufficient for most cases.

    * ``add_custom_data_to_omsi_file``: The default implementation is empty as the default data write is  managed by the \
    `omsi_file_experiment.create_analysis()` function.  Overwrite this function, in case that the analysis needs \
    to write data to the HDF5 omsi file beyond what the defualt omsi data API does.

    * ``read_from_omsi_file``: The default implementation tries to reconstruct the original data as far as possible, \
    however, in particular in case that a custom add_custom_data_to_omsi_file function has been implemented, the \
    default implementation may not be sufficien. The default implementation reconstructs: i) analysis_identifier \
    and reads all custom data into ii)__data_list. Note, an error will be raised in case that the analysis type \
    specified in the HDF5 file does not match the analysis type specified by get_analysis_type(). This function \
    can be optionally overwritten to implement a custom data read.

    **Viewer functions:**

    Several convenient functions are used to allow the OpenMSI online viewer to interact with the analysis \
    and to visualize it. The default implementations provided here simply indicate that the analysis does not \
    support the data access operations required by the online viewer. Overwrite these functions in the derived \
    analysis classes in order to interface them with the viewer. All viewer-related functions start with ``v\_...`` .

    NOTE: the default implementation of the viewer functions defined in ``analysis_base`` are \
    designed to take care of the common requirement for providing viewer access to data from all dependencies \
    of an analysis. In many cases, the default implementation is often sill called at the end of custom \
    viewer functions.

    NOTE: The viewer functions typically support a viewer_option parameter. viewer_option=0 is expected to  \
    refer to the analysis itself.

    * ``v_qslice``: Retrieve/compute data slices as requested via qslice URL requests. The corresponding view \
    of the DJANGO data access server already translates all input parameters and takes care of generating images/plots \
    if needed. This function is only responsible for retrieving the data.
    * ``v_qspectrum``: Retrieve/compute spectra as requested via qspectrum URL requests. The corresponding view of \
    the DJANGO data access server already translates all input parameters and takes care of generating images/plots \
    if needed. This function is only responsible for retrieving the data.
    * ``v_qmz``: Define the m/z axes for image slices and spectra as requested by qspectrum URL requests.
    * ``v_qspectrum_viewer_options``: Define a list of strings, describing the different viewer options available \
    for the analysis for qspectrum requests (i.e., ``v_qspectrum``). This feature allows the analysis developer \
    to define multiple different visualization modes for the analysis. For example, when performing a data reduction \
    (e.g., PCA or NMF) one may want to show the raw spectra or the loadings vector of the projection in the spectrum \
    view (v_qspectrum). By providing different viewer options we allow the user to decide which option they are \
    most interested in.
    * ``v_qslice_viewer_options``: Define a list of strings, describing the different viewer options available for \
    the analysis for qslice requests (i.e., ``v_qslice``). This feature allows the analysis developer to define \
    multiple different visualization modes for the analysis. For example, when performing a data reduction \
    (e.g., PCA or NMF) one may want to show the raw spectra or the loadings vector of the projection in the spectrum \
    view (v_qspectrum). By providing different viewer options we allow the user to decide which option they \
    are most interested in.
    """

    _analysis_instances = set()
    """
    Class variable used to track all instances of analysis_base
    """

    def __init__(self):
        """Initialize the basic data members"""
        self.analysis_identifier = "undefined"
        self.__data_list = []
        self.parameters = []
        self.data_names = []
        self.run_info = run_info_dict()
        self.profile_time_and_usage = False
        self.profile_memory = False
        self.omsi_analysis_storage = []
        self._analysis_instances.add(weakref.ref(self))
        self.mpi_comm = mpi_helper.get_comm_world()
        self.mpi_root = 0

    def __getitem__(self,
                    key):
        """
        This class supports basic slicing to access data stored in the main member variables.
        By default the data is retrieved from __data_list and the __getitem__(key) function.
        which implemtent the [..] operator, returns __data_list[key]['data']. The key is
        a string indicating the name of the parameter to be retrieved. If the key is not
        found in the __data_list then the function will try to retrieve the data from
        the self.parameters list.
        """
        if isinstance(key, str) or isinstance(key, unicode):
            for i in self.__data_list:
                if i['name'] == key:
                    return i['data']
            for i in self.parameters:
                if i['name'] == key:
                    return i.get_data_or_default()
            if key in self.data_names:
                return dependency_dict(param_name=None,
                                       link_name=None,
                                       dataname=key,
                                       omsi_object=self,
                                       selection=None,
                                       help=None)
            return None
        else:
            return None

    def __setitem__(self,
                    key,
                    value):
        """
        Set values in the __data, or parameters lists.
        If the given key is found in the parameters list then it is assigned
        to the paramerters/dependencies, otherwise the key is assumed to be a
        an output that needs to be added to the __data_list
        """
        if key in self.get_parameter_names():
            self.set_parameter_values(**{key: value})
            self.omsi_analysis_storage = []
        elif key in self.data_names:
            if 'numpy' not in str(type(value)):
                temp_value = np.asarray(value)
                ana_data = analysis_data(name=key,
                                         data=temp_value,
                                         dtype=temp_value.dtype)
            else:
                ana_data = analysis_data(name=key,
                                         data=value,
                                         dtype=value.dtype)
            index = None
            for obj_index, ana_data_obj in enumerate(self.__data_list):
                if ana_data_obj['name'] == key:
                    index = obj_index
                    break
            if index is None:
                self.__data_list.append(ana_data)
            else:
                self.__data_list[index] = ana_data
            self.omsi_analysis_storage = []
        else:
            raise KeyError('Invalid key. The given key was not found as part of the analysis parameters nor output.')

    @classmethod
    def get_analysis_instances(cls):
        """
        Generator function used to iterate through all instances of analysis_base.
        The function creates references for all weak references stored in cls._analysis_instances
        and returns the references if it exists and cleans up the any invalid references after the
        iteration is complete.
        :return: References to analysis_base objects
        """
        invalid_references = set()
        for ref in cls._analysis_instances:
            obj = ref()
            if obj is not None:
                yield obj
            else:
                invalid_references.add(ref)
        cls._analysis_instances -= invalid_references

    @classmethod
    def locate_analysis(cls,
                        data_object,
                        include_parameters=False):
        """
        Given a data_object try to locate the analysis that creates the object as an
        output of its execution.

        :param data_object: The data object of interest.
        :param include_parameters: Boolean indicating whether also input parameters should be considered
            in the search in addition to the outputs of an analysis

        :return: dependency_dict pointing to the relevant object or None in case the
            object was not found.
        """
        for ana_obj in cls.get_analysis_instances():
            ana_params_and_outputs = ana_obj.get_analysis_data_names()
            if include_parameters:
                ana_params_and_outputs += ana_obj.get_parameter_names()
            for dataname in ana_params_and_outputs:
                obj = ana_obj[dataname]
                if obj is data_object:
                    if type(obj) not in (float, int, bool, long, complex, str, unicode):
                        return dependency_dict(param_name=None,
                                               link_name=None,
                                               dataname=dataname,
                                               omsi_object=ana_obj,
                                               selection=None,
                                               help=None)

        return None

    def update_analysis_parameters(self, **kwargs):
        """
        Record the analysis parameters pass to the execute() function.

        The default implementation simply calls the set_parameter_values(...) function.
        This function may be overwritten to customize the behavior of how parameters
        are recorded by the execute function.

        :param kwargs: Dictionary of keyword arguments with the parameters passed to the execute(..) function

        """
        self.set_parameter_values(**kwargs)

    def define_missing_parameters(self):
        """
        Called by the execute function before self.update_analysis_parameters
        to set any required parameters that have not been defined to their respective default values.

        This function may be overwritten in child classes to customize
        the definition of default parameter values and to apply any
        modifications (or checks) of parameters before the analysis is executed.
        Any changes applied here will be recorded in the parameter of the analysis.
        """
        for param in self.parameters:
            if param['required'] and not param.data_set():
                param['data'] = param['default']

    def check_ready_to_execute(self):
        """
        Check if all inputs are ready to determine if the analysis is ready to run.

        :return: List of omsi_analysis_parameter objects that are not ready. If the
            returned list is empty, then the analysis is ready to run.
        """
        pending_indputs = []
        for param in self.parameters:
            if not param.data_ready():
                pending_indputs.append(param)
        return pending_indputs

    def record_execute_analysis_outputs(self, analysis_output):
        """
        Function used internally by execute to record the output
        of the custom execute_analysis(...) function to the __data_list.

        This function may be overwritten in child classes in order to
        customize the behavior for recording data outputs. Eg., for some
        analyses one may only want to record a particular set of outputs,
        rather than all outputs generated by the analysis.

        :param analysis_output: The output of the execute_analysis(...) function to be recorded
        """
        # Record the analysis output so that we can save it to file
        if analysis_output is not None:
            if len(self.data_names) == 1:   # We need this case, because analysis_output is not a tuple we can slice
                self[self.data_names[0]] = analysis_output
            else:
                for data_index, data_name in enumerate(self.data_names):
                    self[data_name] = analysis_output[data_index]

    def execute(self, **kwargs):
        """
        Use this function to run the analysis.

        :param kwargs: Parameters to be used for the analysis. Parameters may also be set using
            the __setitem__ mechanism or as baches using the set_parameter_values function.

        :returns: This function returns the output of the execute analysis function.

        :raises: AnalysisReadyError in case that the analysis is not ready to be executed. This may be
            the case, e.g, when a dependent input parameter is not ready to be used.

        """
        # Import modules for profiling if needed
        if self.profile_time_and_usage:
            try:
                from cProfile import Profile
            except ImportError:
                try:
                    from profile import Profile
                except ImportError:
                    self.profile_time_and_usage = False
                    warnings.warn("Profiling of run failed due to import error. Could not find cProfile or profile.")
            try:
                import pstats
            except ImportError:
                warnings.warn("Profiling of run failed due to import error for pstats module")
                self.profile_time_and_usage = False
        if self.profile_memory:
            try:
                import memory_profiler
            except ImportError:
                self.profile_memory = False
                warnings.warn("Profiling of memory failed due to import error. Could not import memory_profiler.")
        if self.profile_time_and_usage or self.profile_memory:
            try:
                import StringIO
            except ImportError:
                self.profile_memory = False
                self.profile_time_and_usage = False
                warnings.warn("All profiling disabled. Could not import StringIO.")

        # 1) Remove the saved analysis object since we are running the analysis again
        self.omsi_analysis_storage = []

        # 2) Define all parameters and make sure that they are ready
        # 2.1) Set any parameters that are given to the execute function
        self.update_analysis_parameters(**kwargs)

        # 2.2) Set the parameters that are required that have a default value but that have not been initialized
        self.define_missing_parameters()

        # 2.3) Check that all parameters are ready to be used
        pending_params = self.check_ready_to_execute()
        if len(pending_params) > 0:
            raise AnalysisReadyError("The analysis is not ready.", pending_params)

        # 3) Record basic execution provenance information prior to running the analysis
        self.run_info.clear()
        self.run_info.record_preexecute()

        # 4) Define the start-time for the execution of our analysis
        start_time = time.time()

        # 5) Run the analysis
        # 5.1) Execute the analysis as is without any profiling
        if not self.profile_time_and_usage and not self.profile_memory:
            analysis_output = self.execute_analysis()
        # 5.2) Execute the analysis with runtime profiling enabled
        else:
            profiler_time_and_use = None
            profiler_mem = None
            # 5.2.1) Profile time and usage only
            if self.profile_time_and_usage and not self.profile_memory:
                # Enable profiling cProfile and execute the analysis
                profiler_time_and_use = Profile()
                profiler_time_and_use.enable()
                analysis_output = self.execute_analysis()
                profiler_time_and_use.disable()
            # 5.2.2) Profile memory usage only
            elif self.profile_memory and not self.profile_time_and_usage:
                profiler_mem = memory_profiler.LineProfiler()
                analysis_output = profiler_mem(self.execute_analysis)()
            # 5.2.3) Profile i) time and usage  and ii) memory usage
            elif self.profile_memory and self.profile_time_and_usage:
                profiler_mem = memory_profiler.LineProfiler()
                profiler_time_and_use = Profile()
                profiler_time_and_use.enable()
                analysis_output = profiler_mem(self.execute_analysis)()
                profiler_time_and_use.disable()

            # 5.3) Record the profiling data
            # 5.3.1) Save the time and usage profiling data from cProfile
            if profiler_time_and_use is not None:
                profiler_time_and_use.create_stats()
                self.run_info['profile'] = unicode(profiler_time_and_use.stats)

                # Save the summary statistics for the profiling data
                stats_io = StringIO.StringIO()
                profiler_stats = pstats.Stats(profiler_time_and_use, stream=stats_io).sort_stats('cumulative')
                profiler_stats.print_stats()
                self.run_info['profile_stats'] = stats_io.getvalue()

            # 5.3.2) Save the results of the memory profiler
            if profiler_mem is not None:
                mem_stats_io = StringIO.StringIO()
                memory_profiler.show_results(profiler_mem, stream=mem_stats_io)
                self.run_info['profile_mem'] = unicode(profiler_mem.code_map)
                self.run_info['profile_mem_stats'] = mem_stats_io.getvalue()

        # Record basic post-execute runtime information and clean up the run-info to remove empty entries
        execution_time = time.time() - start_time
        self.run_info.record_postexecute(execution_time=execution_time)
        self.run_info.clean_up()

        # If we ran the analysis in parallel, then collect all runtime information
        if mpi_helper.MPI_AVAILABLE:
            self.run_info = self.run_info.gather(root=self.mpi_root,
                                                 comm=self.mpi_comm)

        # Record the analysis output
        self.record_execute_analysis_outputs(analysis_output=analysis_output)

        # Return the output of the analysis
        return analysis_output

    def execute_analysis(self):
        """
        Implement this function to implement the execution of the actual analysis.

        This function may not require any input parameters. All input parameters are
        recorded in the parameters and dependencies lists and should be retrieved
        from there, e.g, using basic slicing self[ paramName ]

        Input parameters may be added for internal use ONLY. E.g, we may add parameters that
        are used internally to help with parallelization of the execute_analysis function.
        Such parameters are not recorded and must be strictly optional so that analysis_base.execute(...)
        can call the function.

        :returns: This function may return any developer-defined data. Note, all
                 output that should be recorded must be put into the data list.

        """
        raise NotImplementedError("Implement execute_analysis in order to be able to run the analysis.")

    @classmethod
    def v_qslice(cls,
                 analysis_object,
                 z,
                 viewer_option=0):
        """
        Get 3D analysis dataset for which z-slices should be extracted for presentation in the OMSI viewer

        :param analysis_object: The omsi_file_analysis object for which slicing should be performed
        :param z: Selection string indicting which z values should be selected.
        :param viewer_option: If multiple default viewer behaviors are available for a given analysis
                            then this option is used to switch between them.

        :returns: numpy array with the data to be displayed in the image slice viewer. Slicing will be
                 performed typically like [:,:,zmin:zmax].

        :raises: NotImplementedError in case that v_qslice is not supported by the analysis.
        """
        from omsi.analysis.omsi_viewer_helper import omsi_viewer_helper
        from omsi.shared.data_selection import check_selection_string, \
            selection_type, \
            selection_string_to_object
        re_slice, re_spectrum, re_slicedata, re_spectrumdata, re_slice_option_index, re_spectrum_option_index = \
            cls.__construct_dependent_viewer_options__(analysis_object)

        # Check whether the given selection is valid
        z_type = check_selection_string(z)
        if z_type == selection_type['invalid']:
            return None
        if isinstance(re_slicedata[viewer_option], omsi_file_msidata):
            try:
                z_select = selection_string_to_object(selection_string=z)
                data = re_slicedata[viewer_option][:, :, z_select]
                return data
            except:
                return None

        elif isinstance(re_slicedata[viewer_option], omsi_file_analysis):
            current_analysis_type = str(re_slicedata[viewer_option].get_analysis_type()[0])
            return omsi_viewer_helper.analysis_name_to_class(current_analysis_type).v_qslice(
                analysis_object=re_slicedata[viewer_option],
                z=z,
                viewer_option=re_slice_option_index[viewer_option])
        else:
            return None

    @classmethod
    def v_qspectrum(cls,
                    analysis_object,
                    x,
                    y,
                    viewer_option=0):
        """
        Get from which 3D analysis spectra in x/y should be extracted for presentation in the OMSI viewer

        **Developer Note:** h5py currently supports only a single index list. If the user provides an index-list
        for both x and y, then we need to construct the proper merged list and load the data manually, or if
        the data is small enough, one can load the full data into a numpy array which supports
        multiple lists in the selection.

        :param analysis_object: The omsi_file_analysis object for which slicing should be performed
        :param x: x selection string
        :param y: y selection string
        :param viewer_option: If multiple default viewer behaviors are available for a given
            analysis then this option is used to switch between them.

        :returns: The following two elements are expected to be returned by this function :

                1) 1D, 2D or 3D numpy array of the requested spectra. NOTE: The mass (m/z) axis must be \
                the last axis. For index selection x=1,y=1 a 1D array is usually expected. For indexList \
                selections x=[0]&y=[1] usually a 2D array is expected. For ragne selections x=0:1&y=1:2 we \
                one usually expects a 3D array.
                2) None in case that the spectra axis returned by v_qmz are valid for the returned spectrum. \
                Otherwise, return a 1D numpy array with the m/z values for the spectrum (i.e., if custom m/z \
                values are needed for interpretation of the returned spectrum).This may be needed, e.g., in \
                cases where a per-spectrum peak analysis is performed and the peaks for each spectrum appear \
                at different m/z values.
        """
        from omsi.analysis.omsi_viewer_helper import omsi_viewer_helper
        from omsi.shared.data_selection import \
            check_selection_string, \
            selection_type, \
            selection_string_to_object   # , selection_to_indexlist
        re_slice, re_spectrum, re_slicedata, re_spectrumdata, re_slice_option_index, re_spectrum_option_index = \
            cls.__construct_dependent_viewer_options__(analysis_object)
        # Check whether the given selection is valid
        x_type = check_selection_string(x)
        y_type = check_selection_string(y)
        x_selection = selection_string_to_object(x)
        y_selection = selection_string_to_object(y)

        if (x_type == selection_type['invalid']) or (y_type == selection_type['invalid']):
            return None, None
        if isinstance(re_spectrumdata[viewer_option], omsi_file_msidata):
            if x_type == selection_type['invalid'] or y_type == selection_type['invalid']:
                return None, None
            if x_type == selection_type['indexlist'] and y_type == selection_type['indexlist']:
                # We now need to match up the index lists and load all the individial values
                # ToDo: This is can be very inefficient for large lists
                x_size = len(x_selection)
                y_size = len(y_selection)
                if x_size != y_size:
                    raise KeyError("Selection lists don't match")
                current_dataset = re_spectrumdata[viewer_option]
                z_size = current_dataset.shape[2]
                # Allocate the required memory
                data = np.zeros((x_size, z_size), dtype=current_dataset.dtype)
                for i in xrange(0, x_size):
                    data[i, :] = current_dataset[x_selection[i], y_selection[i], :]
            else:
                data = re_spectrumdata[viewer_option][x_selection, y_selection, :]

            return data, None
        elif isinstance(re_spectrumdata[viewer_option], omsi_file_analysis):
            current_analysis_type = str(re_spectrumdata[viewer_option].get_analysis_type()[0])
            return omsi_viewer_helper.analysis_name_to_class(current_analysis_type).v_qspectrum(
                analysis_object=re_spectrumdata[viewer_option],
                x=x,
                y=y,
                viewer_option=re_spectrum_option_index[viewer_option])
        else:
            return None, None

    @classmethod
    def v_qmz(cls,
              analysis_object,
              qslice_viewer_option=0,
              qspectrum_viewer_option=0):
        """
        Get the mz axes for the analysis

        :param analysis_object: The omsi_file_analysis object for which slicing should be performed
        :param qslice_viewer_option: If multiple default viewer behaviors are available for a given
            analysis then this option is used to switch between them for the qslice URL pattern.
        :param qspectrum_viewer_option: If multiple default viewer behaviors are available for a
            given analysis then this option is used to switch between them for the qspectrum URL pattern.

        :returns: The following four arrays are returned by the analysis:

            - mzSpectra : Array with the static mz values for the spectra.
            - labelSpectra : Lable for the spectral mz axis
            - mzSlice : Array of the static mz values for the slices or None if identical to the mzSpectra.
            - labelSlice : Lable for the slice mz axis or None if identical to labelSpectra.

        """
        from omsi.analysis.omsi_viewer_helper import omsi_viewer_helper
        re_slice, re_spectrum, re_slicedata, re_spectrumdata, re_slice_option_index, re_spectrum_option_index = \
            cls.__construct_dependent_viewer_options__(analysis_object)
        mz_spectra = None
        label_spectra = None
        mz_slice = None
        label_slice = None
        # Determine the spectra mz axis
        if len(re_spectrum) > 0:
            if isinstance(re_spectrumdata[qspectrum_viewer_option], omsi_file_msidata):
                mz_spectra = re_spectrumdata[qspectrum_viewer_option].mz[:]
                label_spectra = "m/z"
            elif isinstance(re_spectrumdata[qspectrum_viewer_option], omsi_file_analysis):
                mz_spectra, label_spectra, temp_a, temp_b = omsi_viewer_helper.get_axes(
                    re_spectrumdata[qspectrum_viewer_option],
                    qslice_viewer_option=re_slice_option_index[qslice_viewer_option],
                    qspectrum_viewer_option=re_spectrum_option_index[qspectrum_viewer_option])
            else:
                mz_spectra = None
                label_spectra = None
        # Determine the slice mz axis
        if len(re_slice) > 0:
            if isinstance(re_slicedata[qslice_viewer_option], omsi_file_msidata):
                mz_slice = re_slicedata[qslice_viewer_option].mz[:]
                label_slice = "m/z"
            elif isinstance(re_slicedata[qslice_viewer_option], omsi_file_analysis):
                temp_a, temp_b, mz_slice, label_slice = \
                    omsi_viewer_helper.get_axes(
                        re_slicedata[qslice_viewer_option],
                        qslice_viewer_option=re_slice_option_index[qslice_viewer_option],
                        qspectrum_viewer_option=re_spectrum_option_index[qspectrum_viewer_option])
            else:
                mz_slice = None
                label_slice = None

        return mz_spectra, label_spectra, mz_slice, label_slice

    @classmethod
    def v_qspectrum_viewer_options(cls,
                                   analysis_object):
        """
        Get a list of strings describing the different default viewer options for the analysis for qspectrum.
        The default implementation tries to take care of handling the spectra retrieval for all the dependencies
        but can naturally not decide how the qspectrum should be handled by a derived class. However, this
        implementation is often called at the end of custom implementations to also allow access to data from
        other dependencies.

        :param analysis_object: The omsi_file_analysis object for which slicing should be performed.
            For most cases this is not needed here as the support for slice operations is usually a static decision
            based on the class type, however, in some cases additional checks may be needed (e.g., ensure that the
            required data is available).

        :returns: List of strings indicating the different available viewer options. The list should be empty if
            the analysis does not support qspectrum requests (i.e., v_qspectrum(...) is not available).

        """
        re_slice, re_spectrum, re_slicedata, re_spectrumdata, re_slice_option_index, re_spectrum_option_index = \
            cls.__construct_dependent_viewer_options__(analysis_object)
        return re_spectrum

    @classmethod
    def v_qslice_viewer_options(cls,
                                analysis_object):
        """
        Get a list of strings describing the different default viewer options for the analysis for qslice.
        The default implementation tries to take care of handling the spectra retrieval for all the dependencies
        but can naturally not decide how the qspectrum should be handled by a derived class. However, this
        implementation is often called at the end of custom implementations to also allow access to data from
        other dependencies.

        :param analysis_object: The omsi_file_analysis object for which slicing should be performed.  For most cases
            this is not needed here as the support for slice operations is usually a static decission based on
            the class type, however, in some cases additional checks may be needed (e.g., ensure that the required
            data is available).

        :returns: List of strings indicating the different available viewer options. The list should be empty
            if the analysis does not support qslice requests (i.e., v_qslice(...) is not available).

        """
        re_slice, re_spectrum, re_slicedata, re_spectrumdata, re_slice_option_index, re_spectrum_option_index = \
            cls.__construct_dependent_viewer_options__(analysis_object)
        return re_slice

    @classmethod
    def __construct_dependent_viewer_options__(cls,
                                               analysis_object):
        """
        Internal helper function to construct the viewer options for analysis dependencies.

        :returns: The following 4 lists:

        * ``re_slice`` : List of names for the slice options
        * ``re_spectrum`` : List of names for the spectrum options
        * ``re_slicedata`` : omsi_file_* API object associated with the slice options. These \
        are either omis_file_analysis or omsi_file_msidata objects.
        * ``re_spectrumdata`` : omsi_file_* API object associated with the slice options. These \
        are either omis_file_analysis or omsi_file_msidata objects.
        * ``re_slice_optionIndex``: List of integrers indicating for the given entry the viewer_option \
        to be used with the re_slicedata object for the given option.
        * ``re_spectrum_optionIndex``: List of integrers indicating for the given entry the viewer_option \
        to be used with the re_spectrumdata object for the given option.
        """
        from omsi.analysis.omsi_viewer_helper import omsi_viewer_helper
        re_slice = []
        re_slicedata = []
        re_slice_option_index = []
        re_spectrum = []
        re_spectrumdata = []
        re_spectrum_option_index = []

        # We don't need to use get_all_dependency_data_recursive here, because when we call
        # omsi_viewer_helper.get_qslice_ .. (spectrum etc.) the recursion to dependent options
        # occurs automatically.
        all_dependencies = analysis_object.get_all_dependency_data()
        for di in all_dependencies:
            # Check if we can slice the data
            if isinstance(di['omsi_object'], omsi_file_msidata):
                re_spectrum.append("Raw Data: " + di['link_name'])
                re_slice.append("Raw Data: " + di['link_name'])
                re_slice_option_index.append(0)
                re_spectrumdata.append(di['omsi_object'])
                re_slicedata.append(di['omsi_object'])
                re_spectrum_option_index.append(0)
            elif isinstance(di['omsi_object'], omsi_file_analysis):
                slice_options = omsi_viewer_helper.get_qslice_viewer_options(di['omsi_object'])
                spectrum_options = omsi_viewer_helper.get_qspectrum_viewer_options(di['omsi_object'])
                for sloption_index in range(0, len(slice_options)):
                    re_slice.append(slice_options[sloption_index])
                    re_slicedata.append(di['omsi_object'])
                    re_slice_option_index.append(sloption_index)
                for sloption_index in range(0, len(spectrum_options)):
                    re_spectrum.append(spectrum_options[sloption_index])
                    re_spectrumdata.append(di['omsi_object'])
                    re_spectrum_option_index.append(sloption_index)
                # analysisType = str(anaObj.get_analysis_type()[0])
                # if omsi_viewer_helper.supports_slice( di['omsi_object']) :
                #     re_slice.append( "Analysis: "+str(di['omsi_object'].get_analysis_identifier()[0]) )
                #     re_slicedata.append( di['omsi_object'] )
                # if omsi_viewer_helper.supports_spectra( di['omsi_object'] ) :
                #     re_spectrum.append( "Analysis: "+str(di['omsi_object'].get_analysis_identifier()[0]) )
                #     re_spectrumdata.append( di['omsi_object'] )
            else:
                warnings.warn("Unknown dependency")
        return re_slice, re_spectrum, re_slicedata, re_spectrumdata, re_slice_option_index, re_spectrum_option_index

    @staticmethod
    def get_default_dtypes():
        """
        Get a list of available default dtypes used for analyses.
        Same as `analysis_dtypes.get_dtypes()`.
        """
        return analysis_dtypes.get_dtypes()

    @staticmethod
    def get_default_parameter_groups():
        """
        Get a list of commonly used parameter groups and associated descriptions.

        Use of default groups provides consistency and allows other system to
        design custom behavior around the semantic of parameter groups

        :return: Dictionary where the keys are the short names of the groups and the
            values are dicts with following keys:value pairs: 'name' , 'description'.
            Use the 'name' to define the group to be used.
        """
        return {'stop': {'name': 'stop conditions',
                         'description': 'Termination criteria for the analysis'},
                'input': {'name': 'input data',
                          'description': 'Input data to be analyzed'},
                'settings': {'name': 'analysis settings',
                             'description': 'Analysis settings'},
                'parallel': {'name': 'parallel settings',
                             'description': 'Parallel execution settings'}}

    def enable_time_and_usage_profiling(self, enable=True):
        """
        Enable or disable profiling of time and usage of code parts of execute_analysis.

        :param enable: Enable (True) or disable (False) profiling
        :type enable: bool

        :raises: ImportError is raised if a required package for profiling is not available.
        """
        if enable != self.profile_time_and_usage:
            if not enable:
                self.profile_time_and_usage = False
            else:
                # Try to import all required packages for profiling
                try:
                    from cProfile import Profile
                except ImportError:
                    from profile import Profile
                import pstats
                import StringIO
                import ast
                self.profile_time_and_usage = True

    def enable_memory_profiling(self, enable=True):
        """
        Enable or disable line-by-line profiling of memory usage of execute_analysis.

        :param enable_memory: Enable (True) or disable (False) line-by-line profiling of memory usage
        :type enable_memory: bool

        :raises: ImportError is raised if a required package for profiling is not available.
        """
        if enable != self.profile_memory:
            if not enable:
                self.profile_memory = False
            else:
                import memory_profiler
                import StringIO
                self.profile_memory = True

    def get_memory_profile_info(self):
        """
        Based on the memory profile of the execute_analysis(..) function get
        the string describing the line-by-line memory usage.

        :return: String describing the memory usage profile. None is returned in case that
            no memory profiling data is available.
        """
        if 'profile_mem_stats' in self.run_info:
            return self.run_info['profile_mem_stats']
        else:
            return None

    def get_profile_stats_object(self, consolidate=True):
        """
        Based on the execution profile of the execute_analysis(..) function get
        ``pstats.Stats`` object to help with the interpretation of the data.

        :param consolidate: Boolean flag indicating whether multiple stats (e.g., from multiple cores)
            should be consolidated into a single stats object. Default is True.

        :return: A single pstats.Stats object if consolidate is True. Otherwise the function
            returns a list of pstats.Stats objects, one per recorded statistic. None is returned
            in case that the stats objects cannot be created or no profiling data is available.
        """
        from pstats import Stats
        from ast import literal_eval
        if 'profile' in self.run_info:
            # Parse the profile data (which is stored as a string) or in the case of MPI we may
            # have a list of strings from each MPI processes
            if isinstance(self.run_info['profile'], list):
                # Convert the profile from each MPI process independently
                profile_data = [literal_eval(profile) for profile in self.run_info['profile']]
            else:
                # If we only have a single stat, then convert our data to a list, so that we can
                # handle the single and multiple statistics case in the same way in the remainder of this function
                profile_data = [literal_eval(self.run_info['profile']), ]

            # Create a list of profile objects that the pstats.Stats class understands
            profile_dummies = []
            for profile_i in profile_data:
                # Here we are creating for each statistic a dummy class on the fly that holds our
                # profile_data in the stats attributes and has an empty create_stats function.
                # This trick allows us to create a pstats.Stats object without having to write our
                # stats data to file or having to create a cProfile.Profile object first. Writing
                # the data to file involves overhead and is ugly and creating a profiler and
                # overwriting its stats is potentially problematic
                profile_dummies.append(type('Profile',
                                            (object,),
                                            {'stats': profile_i, 'create_stats': lambda x: None})())

            # Create the statistics object and return it
            if consolidate:
                profile_stats = Stats(*profile_dummies)
                return profile_stats
            else:
                profile_stats = [Stats(profile_i) for profile_i in profile_dummies]
                return profile_stats
        else:
            return None

    def get_help_string(self):
        """
        Get a string describing the analysis.

        :return: Help string describing the analysis and its parameters
        """
        from omsi.workflow.analysis_driver.omsi_cl_driver import omsi_cl_driver
        temp_driver = omsi_cl_driver(analysis_class=self.__class__)
        temp_driver.initialize_argument_parser()
        return temp_driver.parser.format_help()

    def get_omsi_analysis_storage(self):
        """
        Get a list of known locations where this analysis has been saved.

        :return: List of `omsi.dataformat.omsi_file.analysis. omsi_file_analysis` objects where the analysis is saved.
        """
        return self.omsi_analysis_storage

    def has_omsi_analysis_storage(self):
        """
        Check whether a storage location is known where the anlaysis has been saved.

        :return: Boolean indicating whether self.omsi_analysis_storage is not empty
        """
        return len(self.omsi_analysis_storage) > 0

    def get_analysis_type(self):
        """
        Return a string indicating the type of analysis performed
        """
        return self.__module__  # self.__class__.__name__

    def get_analysis_data_names(self):
        """
        Get a list of all analysis dataset names.
        """
        return self.data_names

    def get_parameter_names(self):
        """
        Get a list of all parameter dataset names (including those that may define
        dependencies.
        """
        return [param['name'] for param in self.parameters]

    def get_analysis_data(self,
                          index):
        """
        Given the index return the associated dataset to be written to the HDF5 file

        :param index : Retrun the index entry of the private member __data_list.
        """
        return self.__data_list[index]

    def get_parameter_data(self,
                           index):
        """
        Given the index return the associated dataset to be written to the HDF5 file

        :param index : Return the index entry of the private member parameters.
        """
        return self.parameters[index]

    def get_analysis_data_by_name(self,
                                  dataname):
        """
        Given the key name of the data return the associated analysis_data object.

        :param dataname: Name of the analysis data requested from the private __data_list member.

        :returns: The analysis_data object or None if not found.
        """
        for i in self.__data_list:
            if i['name'] == dataname:
                return i
        return None

    def get_parameter_data_by_name(self,
                                   dataname):
        """
        Given the key name of the data return the associated parameter_data object.

        :param dataname: Name of the parameter requested from the parameters member.

        :returns: The parameter_data object or None if not found
        """
        for i in self.parameters:
            if i['name'] == dataname:
                return i
        return None

    def get_all_run_info(self):
        """Get the dict with the complete info about the last run of the analysis"""
        return self.run_info

    def get_all_analysis_data(self):
        """Get the complete list of all analysis datasets to be written to the HDF5 file"""
        return self.__data_list

    def get_all_parameter_data(self,
                               exclude_dependencies=False):
        """
        Get the complete list of all parameter datasets to be written to the HDF5 file

        :param exclude_dependencies: Boolean indicating whether we should exclude parameters
            that define dependencies from the list
        """
        if exclude_dependencies:
            return [param for param in self.parameters if not param.is_dependency()]
        else:
            return self.parameters

    def get_all_dependency_data(self):
        """
        Get the complete list of all direct dependencies to be written to the HDF5 file

        NOTE: These are only the direct dependencies as specified by the analysis itself.
        Use  get_all_dependency_data_recursive(..) to also get the indirect decencies of
        the analysis due to dependencies of the decencies themselves.

        :returns: List of parameter_data objects that define dependencies.

        """
        dependency_list = []
        for param in self.parameters:
            if param.is_dependency():
                dependency_list.append(param)
        return dependency_list

    def get_num_analysis_data(self):
        """Retrun the number of analysis datasets to be wirtten to the HDF5 file"""
        return len(self.__data_list)

    def get_num_parameter_data(self):
        """Retrun the number of parameter datasets to be wirtten to the HDF5 file"""
        return len(self.parameters)

    def get_num_dependency_data(self):
        """Return the number of dependencies to be wirtten to the HDF5 file"""
        return len(self.get_all_dependency_data())

    def keys(self):
        """
        Get a list of all valid keys, i.e., a combination of all input parameter and output names.

        :return: List of strings with all input parameter and output names.
        """
        return self.get_analysis_data_names() + self.get_parameter_names()

    def clear_analysis_data(self):
        """Clear the list of analysis data"""
        self.__data_list = []

    def clear_parameter_data(self):
        """Clear the list of parameter data"""
        for param in self.parameters:
            param.clear_data()

    def clear_analysis(self):
        """Clear all analysis, parameter and dependency data"""
        self.clear_analysis_data()
        self.clear_parameter_data()

    def set_parameter_values(self,
                             **kwargs):
        """
        Set all parameters given as input to the function. The inputs
        are placed in the self.parameters list. If the parameter refers
        to an existing h5py.Dataset, h5py.Group,  managed h5py object,
        or is an instance of an existing omis_analysi_base object, then
        a dependency_dict will be created and stored as value instead.

        :param kwargs: Dictionary of keyword arguments. All keys are
               expected to be strings. All values are expected to be
               either i) numpy arrays, ii) int, float, str or unicode
               variables, iii) h5py.Dataset or  h5py.Group, iv) or any
               the omsi_file API class objects. For iii) and iv) one
               may provide a tuple consisting of the dataobject t[0] and
               an additional selection string t[1].
        """
        import h5py
        from omsi.dataformat.omsi_file.common import omsi_file_common
        for k, v in kwargs.items():
            name = unicode(k)
            value = v
            selection = None
            curr_parameter = self.get_parameter_data_by_name(name)
            dtype = curr_parameter['dtype']   # unicode
            if isinstance(v, tuple):
                value = v[0]
                selection = v[1]
            if isinstance(value, h5py.Dataset) or \
                    isinstance(value, h5py.Group) or \
                    omsi_file_common.is_managed(value) or \
                    isinstance(value, analysis_base):
                value = dependency_dict(param_name=name,
                                        link_name=name,
                                        omsi_object=value,
                                        selection=selection,
                                        help=curr_parameter['help'],
                                        dependency_type=dependency_dict.dependency_types['parameter'])
                # dtype = analysis_dtypes.get_dtypes()['ndarray']
            elif isinstance(value, dependency_dict):
                # Set any possibly missing parameters
                value['param_name'] = name
                value['link_name'] = name
                value['help'] = curr_parameter['help']
                value['dependency_type'] = dependency_dict.dependency_types['parameter']
            else:
                # Try to locate the input parameter to see if it is an output of another analysis
                check_param = self.locate_analysis(value)
                # The given parameter value is the output of another analysis so we create a link to it
                if check_param is not None:
                    check_param['param_name'] = name  # Define the name of the dependent parameter
                    check_param['link_name'] = name   # Define the name of the object when stored to file
                    # If the analysis has been saved to file already, then change the dependency to point
                    # to the corresponding file object instead
                    # if len(check_param['omsi_object'].get_omsi_analysis_storage()) > 0:
                    #    check_param['omsi_object'] = check_param['omsi_object'].omsi_analysis_storage[0]

                    # Since we have the data still in memory, add a reference to the data to the
                    # dependency to use the in-memory data rather then forcing a data load from file
                    check_param._force_set_data(value)
                    value = check_param
                # If the input could not be located as an output of another analysis
                else:
                    try:
                        dtype = value.dtype  # if the object specifies a valid numpy dtype
                    except AttributeError:
                        if isinstance(value, float) or \
                                isinstance(value, int) or \
                                isinstance(value, bool) or \
                                isinstance(value, long) or \
                                isinstance(value, complex):
                            value = np.asarray([value])
                            # dtype = value.dtype
                        elif isinstance(value, str) or isinstance(value, unicode):
                            # dtype = omsi_format_common.str_type
                            pass
                        else:
                            value = np.asarray(value)
                            # dtype = value.dtype

            # Parameter set
            if curr_parameter is not None:
                # curr_parameter['dtype'] = dtype
                curr_parameter['data'] = value
            else:  # If used correctly this should not happen. Ensures that we don't omit any data
                warnings.warn('Parameter ' + name + " not found in analysis_base.set_parameter_values(). " +
                              "Adding a new parameter.")
                self.parameters.append(parameter_data(name=name,
                                                      help='',
                                                      dtype=dtype,
                                                      required=False,
                                                      data=value))

    def add_parameter(self,
                      name,
                      help,
                      dtype=unicode,
                      required=False,
                      default=None,
                      choices=None,
                      data=None,
                      group=None):
        """
        Add a new parameter for the analysis. This function is typically used in the constructor
        of a derived analysis to specify the parameters of the analysis.

        :param name: The name of the parameter
        :param help: Help string describing the parameter
        :param type: Optional type. Default is string.
        :param required: Boolean indicating whether the parameter is required (True) or optional (False). Default False.
        :param default: Optional default value for the parameter. Default None.
        :param choices: Optional list of choices with allowed data values. Default None, indicating no choices set.
        :param data: The data assigned to the parameter. None by default.
        :param group: Optional group string used to organize parameters. Default None, indicating that
            parameters are automatically organized by driver class (e.g. in required and optional parameters)

        :raises: ValueError is raised if the parameter with the given name already exists.
        """
        if self.get_parameter_data_by_name(name) is not None:
            raise ValueError('A parameter with the name ' + unicode(name) + " already exists.")
        self.parameters.append(parameter_data(name=name,
                                              help=help,
                                              dtype=dtype,
                                              required=required,
                                              default=default,
                                              choices=choices,
                                              data=data,
                                              group=group))

#    def add_analysis_data(self , name, data, dtype ) :
#        """Add a new dataset to the list of data to be written to the HDF5 file
#
#          The input parameters will be transformed into a analysis_data dictionary.
#
#          :param name: The name for the dataset in the HDF5 format
#          :param data: The numpy array to be written to HDF5. The data write function
#                omsi_file_experiment.create_analysis used for writing of the data to file can
#                in principal also handel other primitive data types by explicitly converting them
#                to numpy. However, in this case the dtype is determined based on the numpy conversion
#                and correct behavior is not guaranteed. I.e., even single scalars should be stored as
#                a 1D numpy array here.
#          :param dtype: The data type to be used during writing. For standard numpy data types this is just
#                 the dtype  of the dataset, i.e., ['data'].dtype. Other allowed datatypes are:
#
#                 * For string:  omsi_format.str_type (omsi_format is located in omsi.dataformat.omsi_file )
#                 * To generate data links: ana_hdf5link   (analysis_data)
#        """
#        self.__data_list.append( analysis_data(name=name, data=data, dtype=dtype) )

#    def add_parameter_data(self , name, data, dtype ) :
#        """Add a new analysis parameter dataset to the list of data to be written to the HDF5 file
#
#           The input parameters will be transformed into a analysis_data dictionary.
#
#          :param name: The name for the dataset in the HDF5 format
#          :param data: The numpy array to be written to HDF5. The data write function
#                omsi_file_experiment.create_analysis used for writing of the data to file can
#                in principal also handel other primitive data types by explicitly converting them
#                to numpy. However, in this case the dtype is determined based on the numpy conversion
#                and correct behavior is not guaranteed. I.e., even single scalars should be stored as
#                a 1D numpy array here.
#          :param dtype: The data type to be used during writing. For standard numpy data types this is just
#                 the dtype  of the dataset, i.e., ['data'].dtype. Other allowed datatypes are:
#
#                 * For string:  omsi_format.str_type (omsi_format is located in omsi.dataformat.omsi_file )
#                 * To generate data links: ana_hdf5link   (analysis_data)
#
#        """
#        self.__parameter_list.append( analysis_data(name=name, data=data, dtype=dtype) )
#

#    def add_dependency_data(self , dependency ) :
#        """Add a new analysis parameter dataset to the list of data to be written to the HDF5 file
#
#          :param dependency: The data that should be added to __dependency_list member to be written to HDF5.
#          :type data: dependency_dict
#
#          :raises: ValueError in case data is not of dependency_dict object.
#        """
#        if isinstance( dependency , dependency_dict ) :
#            self.__dependency_list.append( dependency )
#        else :
#             raise ValueError( "Invalid input for add_data_dependency function" )

    def write_analysis_data(self, analysis_group=None):
        """
        This function used to write the actual analysis data to file. If not implemented, then the
        omsi_file_analysis API's default behavior is used instead.

        :param analysis_group: The h5py.Group object where the analysis is stored. May be None on cores that
            do not perform any writing but which need to participate in communication, e.g., to collect data
            for writing.

        """
        # The default implementation does roughly the following
        # from omsi.dataformat.omsi_file.analysis import omsi_file_analysis
        # for ana_data in self..get_all_analysis_data():
        #        omsi_file_analysis.__write_omsi_analysis_data__(analysis_group, ana_data)
        raise NotImplementedError

    def add_custom_data_to_omsi_file(self, analysis_group):
        """
        This function can be optionally overwritten to implement a custom data write
        function for the analysis to be used by the omsi_file API.

        Note, this function should be used only to add additional data to the analysis
        group. The data that is written by default is still written by
        the `omsi_file_experiment.create_analysis()` function, i.e., the following data is
        written by default: i) analysis_identifier ,ii) get_analysis_type, iii)__data_list,
        iv) parameters, v) runinfo . Since the `omsi_file.experiment.create_analysis()`
        functions takes care of setting up the basic structure of the analysis storage
        (included the subgroubs for storing parameters and data dependencies) this setup can generally
        be assumed to exist before this function is called. This function is called
        automatically at the end omsi_file.experiment.create_analysis() (i.e, actually
        `omsi_file_analysis.__populate_analysis__(..)` so that this function typically does not need to
        be called explicitly.

        :param analysis_group: The h5py.Group object where the analysis is stored.

        """
        pass

    def read_from_omsi_file(self,
                            analysis_object,
                            load_data=True,
                            load_parameters=True,
                            load_runtime_data=True,
                            dependencies_omsi_format=True,
                            ignore_type_conflict=False):
        """
        This function can be optionally overwritten to implement a custom data read.

        The default implementation tries to reconstruct the original data as far
        as possible, however, in particular in case that a custom add_custom_data_to_omsi_file
        function has been implemented, the default implementation may not be sufficient.
        The default implementation reconstructs: i) analysis_identifier and reads all
        custom data into iii)__data_list. Note, an error will be raised in case that
        the analysis type specified in the HDF5 file does not match the analysis type
        specified by get_analysis_type()

        :param analysis_object: The omsi_file_analysis object associated with the hdf5 data group with \
            the analysis data_list
        :param load_data: Should the analysis data be loaded from file (default) or just stored as h5py data objects
        :param load_parameters: Should parameters be loaded from file (default) or just stored as h5py data objects.
        :param load_runtime_data: Should runtime data be loaded from file (default) or just stored as h5py data objects
        :param dependencies_omsi_format: Should dependencies be loaded as omsi_file API objects (default)
            or just as h5py objects.
        :param ignore_type_conflict: Set to True to allow the analysis to be loaded into the
               current analysis object even if the type indicated in the file does not match the
               class. Default value is False. This behavior can be useful when different analysis
               have compatible data structures or when we want to load the data in to a generic
               analysis container, e.g, analysis_generic.

        :returns bool: Boolean indicating whether the data was read successfully

        :raise: TypeError : A type error will be raised in case that the analysis type specified \
        by the file does not match the analysis type provided by self.get_analysis_type()


        """
        if not ignore_type_conflict:
            if str(analysis_object.get_analysis_type()[0]) != str(self.get_analysis_type()):
                error_message = "The type of the analysis specified in the omsi data file " + \
                                "does not match the analysis type of the object " +\
                                str(analysis_object.get_analysis_type()[0]) + \
                                " != " + str(self.get_analysis_type())
                raise TypeError(error_message)

        identifier = analysis_object.get_analysis_identifier()
        if identifier is not None:
            self.analysis_identifier = identifier[0]
        else:
            warnings.warn("The analysis identifier could not be read from the omsi file")

        self.__data_list = analysis_object.get_all_analysis_data(load_data=load_data)
        parameter_list = analysis_object.get_all_parameter_data(load_data=load_parameters,
                                                                exclude_dependencies=False)
        parameters_values = {param['name']: param['data'] for param in parameter_list}
        self.clear_parameter_data()
        self.set_parameter_values(**parameters_values)
        self.run_info = analysis_object.get_all_runinfo_data(load_data=load_runtime_data)
        self.omsi_analysis_storage.append(analysis_object)
        return True

    def get_analysis_identifier(self):
        """Return the name of the analysis used as key when searching for a particular analysis"""
        return self.analysis_identifier

    def set_analysis_identifier(self,
                                identifier):
        """Set the name of the analysis to newName

           :param identifier: The new analysis identifier string to be used (should be unique)
           :type identifier: str
        """
        self.analysis_identifier = identifier

