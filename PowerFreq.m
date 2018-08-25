function [P_required] = PowerFreq(Fr)
% Function converts the grid frequency data into a required power output.
% This is achieved linearly over a certain range, but when the frequency is
% within a specified limit then the required output can be zero. 

%% Nomenclature 
% Definitions of constants and variables in the function

% Fr - Frequency of grid at specified time in Hz.
% P_required - the power that must be supplied by the ESS in MW.

%% Relation

if Fr > 49.99 && Fr < 50.01
    P_required = 0;
else 
    P_required = -19.9074*Fr + 995.3176;
end
end
